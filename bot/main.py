import logging
from datetime import date, time, timezone, timedelta

from telegram.ext import Application, CommandHandler, MessageHandler, filters

DUBAI_TZ = timezone(timedelta(hours=4))

from bot.config import load_settings
from bot.db import init_db, get_setting
from bot.handlers import (
    start_handler,
    help_handler,
    voice_handler,
    date_handler,
    yesterday_handler,
    analyze_handler,
    analyze_week_handler,
    analyze_all_handler,
    status_handler,
    last_meal_handler,
)
from bot.checklist import build_checklist_handler
from bot.oura import fetch_and_store  # used by daily_oura_job

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def evening_checklist_reminder(context) -> None:
    """Scheduled job: remind user to fill in the daily checklist."""
    settings = context.bot_data["settings"]
    chat_id = get_setting(settings.db_path, "chat_id")
    if chat_id:
        today = date.today().isoformat()
        await context.bot.send_message(
            chat_id,
            f"Time to log your daily checklist for {today}.\n"
            f"Tap /checklist to start.",
        )


async def daily_oura_job(context) -> None:
    """Scheduled job: fetch yesterday's Oura data."""
    settings = context.bot_data["settings"]
    from datetime import date, timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    chat_id = get_setting(settings.db_path, "chat_id")

    try:
        data = fetch_and_store(settings.oura_personal_token, settings.db_path, yesterday)
        sleep = data.get("sleep") or {}
        hr = sleep.get("lowest_heart_rate", "N/A")
        hrv = sleep.get("average_hrv", "N/A")
        if chat_id:
            await context.bot.send_message(chat_id, f"Oura daily pull ({yesterday}): HR {hr}, HRV {hrv}")
    except Exception as e:
        logger.exception("Daily Oura job failed")
        if chat_id:
            await context.bot.send_message(chat_id, f"Oura daily pull failed: {e}")


def main() -> None:
    settings = load_settings()
    init_db(settings.db_path)

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings

    # Commands
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("date", date_handler))
    app.add_handler(CommandHandler("yesterday", yesterday_handler))
    app.add_handler(CommandHandler("analyze", analyze_handler))
    app.add_handler(CommandHandler("analyze_week", analyze_week_handler))
    app.add_handler(CommandHandler("analyze_all", analyze_all_handler))
    app.add_handler(CommandHandler("status", status_handler))

    # Checklist conversation (must be added before the generic voice handler)
    app.add_handler(build_checklist_handler())

    # "l" / "L" shortcut for last meal time (after checklist so it doesn't interfere)
    app.add_handler(MessageHandler(filters.Regex(r"^[lL]$"), last_meal_handler))

    # Voice notes
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))

    # Daily job
    job_queue = app.job_queue
    job_queue.run_daily(
        daily_oura_job,
        time=time(hour=settings.oura_pull_hour, minute=0, tzinfo=DUBAI_TZ),
        name="daily_oura",
    )
    job_queue.run_daily(
        evening_checklist_reminder,
        time=time(hour=settings.checklist_reminder_hour, minute=settings.checklist_reminder_minute, tzinfo=DUBAI_TZ),
        name="evening_checklist",
    )

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
