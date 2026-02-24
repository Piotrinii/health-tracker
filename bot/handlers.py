import logging
from datetime import date, datetime, timedelta, timezone

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db import save_transcript, get_stats, set_setting, save_last_meal_time
from bot.transcribe import transcribe_voice
from bot.oura import fetch_and_store, backfill
from bot.analysis import run_analysis

DUBAI_TZ = timezone(timedelta(hours=4))

logger = logging.getLogger(__name__)


def _get_settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _get_settings(context)
    chat_id = str(update.effective_chat.id)
    set_setting(settings.db_path, "chat_id", chat_id)
    await update.message.reply_text(
        "Health tracker active. I'll store your voice notes and pull Oura data daily.\n\n"
        "Commands:\n"
        "/checklist [date] - fill in daily RHR factors checklist\n"
        "/analyze [days] - analyze patterns (default 30 days)\n"
        "/analyze_week - analyze last 7 days\n"
        "/pull_oura [date] - manually fetch Oura data\n"
        "/backfill YYYY-MM-DD YYYY-MM-DD - fetch a date range from Oura\n"
        "/status - see data counts\n"
        "/help - show this message"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me a voice note about your day and I'll transcribe and store it.\n\n"
        "/checklist [date] - daily RHR factors checklist\n"
        "/analyze [days] - run AI analysis on your data (default 30 days)\n"
        "/analyze_week - analyze last 7 days\n"
        "/pull_oura [date] - fetch Oura data for a date (default: yesterday)\n"
        "/backfill START END - fetch Oura data for a date range (YYYY-MM-DD)\n"
        "/status - see how much data you have\n"
    )


async def date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the date for the next voice note. E.g. /date 2026-02-19 or /yesterday"""
    args = context.args
    if args:
        context.user_data["next_date"] = args[0]
        await update.message.reply_text(f"Next voice note will be saved under {args[0]}. Record it now.")
    else:
        await update.message.reply_text("Usage: /date YYYY-MM-DD")


async def yesterday_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shortcut to tag next voice note as yesterday."""
    day = (date.today() - timedelta(days=1)).isoformat()
    context.user_data["next_date"] = day
    await update.message.reply_text(f"Next voice note will be saved under {day}. Record it now.")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _get_settings(context)
    voice = update.message.voice
    await update.message.reply_text("Transcribing...")

    try:
        file = await voice.get_file()
        ogg_bytes = await file.download_as_bytearray()
        text = transcribe_voice(settings.openai_api_key, bytes(ogg_bytes), settings.whisper_model)
        # Use pinned date if set, otherwise today
        day = context.user_data.pop("next_date", None) or date.today().isoformat()
        save_transcript(settings.db_path, day, text, duration_s=voice.duration, file_id=voice.file_id)
        word_count = len(text.split())
        await update.message.reply_text(f"Saved for {day} ({voice.duration}s, {word_count} words):\n\n{text[:500]}")
    except Exception as e:
        logger.exception("Voice handler error")
        await update.message.reply_text(f"Error transcribing: {e}")


async def pull_oura_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _get_settings(context)
    args = context.args
    day = args[0] if args else (date.today() - timedelta(days=1)).isoformat()

    await update.message.reply_text(f"Fetching Oura data for {day}...")
    try:
        data = fetch_and_store(settings.oura_personal_token, settings.db_path, day)
        sleep = data.get("sleep") or {}
        hr = sleep.get("lowest_heart_rate", "N/A")
        hrv = sleep.get("average_hrv", "N/A")
        await update.message.reply_text(f"Stored: Resting HR {hr} bpm, HRV {hrv} ms")
    except Exception as e:
        logger.exception("Oura pull error")
        await update.message.reply_text(f"Error: {e}")


async def backfill_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _get_settings(context)
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /backfill YYYY-MM-DD YYYY-MM-DD")
        return

    start, end = args[0], args[1]
    await update.message.reply_text(f"Backfilling Oura data from {start} to {end}...")
    try:
        count = backfill(settings.oura_personal_token, settings.db_path, start, end)
        await update.message.reply_text(f"Done. Stored {count} days of data.")
    except Exception as e:
        logger.exception("Backfill error")
        await update.message.reply_text(f"Error: {e}")


async def analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _get_settings(context)
    args = context.args
    days_back = int(args[0]) if args else 30

    await update.message.reply_text(f"Analyzing {days_back} days of data...")
    try:
        result = run_analysis(settings.anthropic_api_key, settings.db_path, settings.analysis_model, days_back)
        # Split long messages at paragraph boundaries
        for chunk in _split_message(result):
            await update.message.reply_text(chunk)
    except Exception as e:
        logger.exception("Analysis error")
        await update.message.reply_text(f"Error running analysis: {e}")


async def analyze_week_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.args = ["7"]
    await analyze_handler(update, context)


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _get_settings(context)
    stats = get_stats(settings.db_path)
    lines = [
        "Status:",
        f"  Voice notes: {stats['transcript_count']}",
        f"  Oura days: {stats['oura_count']}",
        f"  Last voice note: {stats['last_transcript_date'] or 'none'}",
        f"  Last Oura data: {stats['last_oura_date'] or 'none'}",
        f"  Last analysis: {stats['last_analysis'] or 'never'}",
    ]
    await update.message.reply_text("\n".join(lines))


async def last_meal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log last meal time when user sends 'l' or 'L'."""
    settings = _get_settings(context)
    now = datetime.now(DUBAI_TZ)
    day = now.date().isoformat()
    time_str = now.strftime("%H:%M")
    save_last_meal_time(settings.db_path, day, time_str)
    await update.message.reply_text(f"Last meal logged at {time_str}")


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find last paragraph break before limit
        split_at = text.rfind("\n\n", 0, max_len)
        if split_at == -1:
            split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
