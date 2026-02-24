"""Daily checklist conversation handler for RHR-influencing factors."""

import logging
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db import save_checklist, get_last_meal_time

logger = logging.getLogger(__name__)

# Conversation states
(
    ELECTRONICS_OFF,
    NASAL_RINSE,
    NASAL_STRIPS,
    MOUTH_TAPING,
    SAUNA,
    DIAPHRAGM_WORK,
    HEAVY_SCREEN,
    TRAINING,
    LAST_MEAL_TIME,
    CAFFEINE_CUTOFF,
    HYDRATION,
    SUPPLEMENTS,
    MEDITATION,
    MEDITATION_MINUTES,
    WAITING_OTHER_TEXT,
) = range(15)

YES_NO_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("Yes", callback_data="1"),
     InlineKeyboardButton("No", callback_data="0"),
     InlineKeyboardButton("Other", callback_data="other")],
])

HYDRATION_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("Good", callback_data="good"),
     InlineKeyboardButton("Poor", callback_data="poor")],
])

TRAINING_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("No training", callback_data="none")],
    [InlineKeyboardButton("Strength", callback_data="strength"),
     InlineKeyboardButton("Cardio", callback_data="cardio")],
    [InlineKeyboardButton("Zone 2", callback_data="zone2"),
     InlineKeyboardButton("Sport", callback_data="sport")],
    [InlineKeyboardButton("Other", callback_data="other")],
])

SUPPLEMENTS_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("None", callback_data="none")],
])

SKIP_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("Skip", callback_data="skip")],
])


def _init_data(context: ContextTypes.DEFAULT_TYPE, for_date: str) -> None:
    context.user_data["checklist"] = {}
    context.user_data["checklist_date"] = for_date


async def checklist_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: /checklist or /checklist YYYY-MM-DD"""
    args = context.args or []
    if args:
        day = args[0]
    else:
        day = date.today().isoformat()

    _init_data(context, day)
    await update.message.reply_text(
        f"Daily checklist for *{day}*\n\nLet's go through it.\n\n"
        "Did you turn off electronics/lights 1h before sleep?",
        reply_markup=YES_NO_KB,
        parse_mode="Markdown",
    )
    return ELECTRONICS_OFF


async def _handle_yn(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, next_q: str, next_state: int, next_kb=None) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "other":
        # Save context so the shared text handler knows where to resume
        context.user_data["other_pending"] = {
            "key": key,
            "next_q": next_q,
            "next_state": next_state,
            "next_kb": next_kb,
        }
        await query.edit_message_text(f"Type your note for this question:")
        return WAITING_OTHER_TEXT

    context.user_data["checklist"][key] = int(query.data)
    await query.edit_message_text(
        f"{'Yes' if query.data == '1' else 'No'} — got it.\n\n{next_q}",
        reply_markup=next_kb or YES_NO_KB,
    )
    return next_state


async def waiting_other_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle free-text input when user picked 'Other' on a yes/no question."""
    text = update.message.text.strip()
    pending = context.user_data.pop("other_pending")
    key = pending["key"]

    # Store the text in other_notes dict, set the integer field to None
    context.user_data["checklist"][key] = None
    other_notes = context.user_data["checklist"].setdefault("other_notes", {})
    other_notes[key] = text

    next_q = pending["next_q"]
    next_state = pending["next_state"]
    next_kb = pending["next_kb"]

    await update.message.reply_text(
        f'"{text}" — got it.\n\n{next_q}',
        reply_markup=next_kb or YES_NO_KB,
    )
    return next_state


async def electronics_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "electronics_off",
                            "Did you rinse your nose?", NASAL_RINSE)


async def nasal_rinse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "nasal_rinse",
                            "Did you use nasal strips?", NASAL_STRIPS)


async def nasal_strips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "nasal_strips",
                            "Mouth taping?", MOUTH_TAPING)


async def mouth_taping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "mouth_taping",
                            "Did you do sauna?", SAUNA)


async def sauna(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "sauna",
                            "Did you do diaphragm work?", DIAPHRAGM_WORK)


async def diaphragm_work(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "diaphragm_work",
                            "Was it a heavy screen/social media day?", HEAVY_SCREEN)


async def heavy_screen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _handle_yn(update, context, "heavy_screen_day",
                            "Training?", TRAINING, next_kb=TRAINING_KB)


async def training(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = query.data
    if val == "none":
        context.user_data["checklist"]["training_type"] = None
        label = "No training"
    elif val == "other":
        await query.edit_message_text("What type of training? (type it)")
        return TRAINING  # stay in same state, wait for text
    else:
        context.user_data["checklist"]["training_type"] = val
        label = val.capitalize()

    # Check if last meal was already logged via "l" shortcut
    settings = context.bot_data["settings"]
    day = context.user_data["checklist_date"]
    logged_meal = get_last_meal_time(settings.db_path, day)
    if logged_meal:
        context.user_data["checklist"]["last_meal_time"] = logged_meal
        await query.edit_message_text(
            f"{label} — got it.\n\nLast meal already logged at {logged_meal}.\n\n"
            "What time was your last caffeine? (HH:MM or type 'skip')",
            reply_markup=SKIP_KB,
        )
        return CAFFEINE_CUTOFF

    await query.edit_message_text(
        f"{label} — got it.\n\nWhat time was your last meal? (HH:MM or type 'skip')",
        reply_markup=SKIP_KB,
    )
    return LAST_MEAL_TIME


async def training_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle free-text training type when user picked 'Other'."""
    context.user_data["checklist"]["training_type"] = update.message.text.strip()

    # Check if last meal was already logged via "l" shortcut
    settings = context.bot_data["settings"]
    day = context.user_data["checklist_date"]
    logged_meal = get_last_meal_time(settings.db_path, day)
    if logged_meal:
        context.user_data["checklist"]["last_meal_time"] = logged_meal
        await update.message.reply_text(
            f"{update.message.text.strip()} — got it.\n\nLast meal already logged at {logged_meal}.\n\n"
            "What time was your last caffeine? (HH:MM or type 'skip')",
            reply_markup=SKIP_KB,
        )
        return CAFFEINE_CUTOFF

    await update.message.reply_text(
        f"{update.message.text.strip()} — got it.\n\nWhat time was your last meal? (HH:MM or type 'skip')",
        reply_markup=SKIP_KB,
    )
    return LAST_MEAL_TIME


async def last_meal_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data["checklist"]["last_meal_time"] = None
        await query.edit_message_text(
            "Skipped.\n\nWhat time was your last caffeine? (HH:MM or type 'skip')",
            reply_markup=SKIP_KB,
        )
    else:
        context.user_data["checklist"]["last_meal_time"] = update.message.text.strip()
        await update.message.reply_text(
            f"{update.message.text.strip()} — got it.\n\nWhat time was your last caffeine? (HH:MM or type 'skip')",
            reply_markup=SKIP_KB,
        )
    return CAFFEINE_CUTOFF


async def caffeine_cutoff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data["checklist"]["caffeine_cutoff"] = None
        await query.edit_message_text(
            "Skipped.\n\nHow was your hydration today?",
            reply_markup=HYDRATION_KB,
        )
    else:
        context.user_data["checklist"]["caffeine_cutoff"] = update.message.text.strip()
        await update.message.reply_text(
            f"{update.message.text.strip()} — got it.\n\nHow was your hydration today?",
            reply_markup=HYDRATION_KB,
        )
    return HYDRATION


async def hydration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["checklist"]["hydration"] = query.data
    await query.edit_message_text(
        f"{query.data.capitalize()} — got it.\n\nAny supplements? Type what you took, or tap None.",
        reply_markup=SUPPLEMENTS_KB,
    )
    return SUPPLEMENTS


async def supplements_btn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["checklist"]["supplements"] = None
    await query.edit_message_text(
        "No supplements.\n\nDid you meditate or do breathwork?",
        reply_markup=YES_NO_KB,
    )
    return MEDITATION


async def supplements_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["checklist"]["supplements"] = update.message.text.strip()
    await update.message.reply_text(
        f"{update.message.text.strip()} — got it.\n\nDid you meditate or do breathwork?",
        reply_markup=YES_NO_KB,
    )
    return MEDITATION


async def meditation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    val = int(query.data)
    context.user_data["checklist"]["meditation"] = val

    if val == 1:
        await query.edit_message_text("How many minutes?")
        return MEDITATION_MINUTES
    else:
        context.user_data["checklist"]["meditation_minutes"] = None
        return await _save_and_summarize(query, context)


async def meditation_minutes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        minutes = int(text)
    except ValueError:
        await update.message.reply_text("Please enter a number (minutes).")
        return MEDITATION_MINUTES

    context.user_data["checklist"]["meditation_minutes"] = minutes
    await update.message.reply_text("Got it.")
    return await _save_and_summarize_msg(update, context)


async def _save_and_summarize(query, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data["checklist"]
    day = context.user_data["checklist_date"]
    settings = context.bot_data["settings"]
    save_checklist(settings.db_path, day, data)

    summary = _format_summary(day, data)
    await query.edit_message_text(summary, parse_mode="Markdown")
    return ConversationHandler.END


async def _save_and_summarize_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data["checklist"]
    day = context.user_data["checklist_date"]
    settings = context.bot_data["settings"]
    save_checklist(settings.db_path, day, data)

    summary = _format_summary(day, data)
    await update.message.reply_text(summary, parse_mode="Markdown")
    return ConversationHandler.END


def _yn(val, other_notes: dict | None = None, key: str = "") -> str:
    if val is None and other_notes and key in other_notes:
        return f"Other: {other_notes[key]}"
    if val is None:
        return "-"
    return "Yes" if val else "No"


def _format_summary(day: str, data: dict) -> str:
    training = data.get("training_type") or "None"
    meal = data.get("last_meal_time") or "-"
    caffeine = data.get("caffeine_cutoff") or "-"
    hydration = (data.get("hydration") or "-").capitalize()
    supps = data.get("supplements") or "None"
    med_min = f" ({data['meditation_minutes']} min)" if data.get("meditation_minutes") else ""
    notes = data.get("other_notes") or {}

    return (
        f"*Checklist saved for {day}*\n\n"
        f"Electronics off 1h before bed: {_yn(data.get('electronics_off'), notes, 'electronics_off')}\n"
        f"Nasal rinse: {_yn(data.get('nasal_rinse'), notes, 'nasal_rinse')}\n"
        f"Nasal strips: {_yn(data.get('nasal_strips'), notes, 'nasal_strips')}\n"
        f"Mouth taping: {_yn(data.get('mouth_taping'), notes, 'mouth_taping')}\n"
        f"Sauna: {_yn(data.get('sauna'), notes, 'sauna')}\n"
        f"Diaphragm work: {_yn(data.get('diaphragm_work'), notes, 'diaphragm_work')}\n"
        f"Heavy screen day: {_yn(data.get('heavy_screen_day'), notes, 'heavy_screen_day')}\n"
        f"Training: {training}\n"
        f"Last meal: {meal}\n"
        f"Last caffeine: {caffeine}\n"
        f"Hydration: {hydration}\n"
        f"Supplements: {supps}\n"
        f"Meditation: {_yn(data.get('meditation'), notes, 'meditation')}{med_min}"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Checklist cancelled.")
    context.user_data.pop("checklist", None)
    context.user_data.pop("checklist_date", None)
    return ConversationHandler.END


def build_checklist_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("checklist", checklist_start)],
        states={
            ELECTRONICS_OFF: [CallbackQueryHandler(electronics_off)],
            NASAL_RINSE: [CallbackQueryHandler(nasal_rinse)],
            NASAL_STRIPS: [CallbackQueryHandler(nasal_strips)],
            MOUTH_TAPING: [CallbackQueryHandler(mouth_taping)],
            SAUNA: [CallbackQueryHandler(sauna)],
            DIAPHRAGM_WORK: [CallbackQueryHandler(diaphragm_work)],
            HEAVY_SCREEN: [CallbackQueryHandler(heavy_screen)],
            TRAINING: [
                CallbackQueryHandler(training),
                MessageHandler(filters.TEXT & ~filters.COMMAND, training_text),
            ],
            LAST_MEAL_TIME: [
                CallbackQueryHandler(last_meal_time),
                MessageHandler(filters.TEXT & ~filters.COMMAND, last_meal_time),
            ],
            CAFFEINE_CUTOFF: [
                CallbackQueryHandler(caffeine_cutoff),
                MessageHandler(filters.TEXT & ~filters.COMMAND, caffeine_cutoff),
            ],
            HYDRATION: [CallbackQueryHandler(hydration)],
            SUPPLEMENTS: [
                CallbackQueryHandler(supplements_btn),
                MessageHandler(filters.TEXT & ~filters.COMMAND, supplements_text),
            ],
            MEDITATION: [CallbackQueryHandler(meditation)],
            MEDITATION_MINUTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, meditation_minutes),
            ],
            WAITING_OTHER_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, waiting_other_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
