import logging
from datetime import date, timedelta

import anthropic

from bot.db import get_transcripts, get_oura_data, get_checklists, save_analysis

logger = logging.getLogger(__name__)


def _yn(val) -> str:
    if val is None:
        return "-"
    return "Yes" if val else "No"


def _build_prompt(transcripts: list[dict], oura_days: list[dict], checklists: list[dict], days_back: int) -> str:
    parts = []
    parts.append(
        "You are a health data analyst. Below is raw data from a personal health tracking system "
        f"covering the last {days_back} days.\n"
    )

    # Voice transcripts
    parts.append("## Voice Note Transcripts\n")
    parts.append(
        "Daily voice notes about training, nutrition, sleep, recovery practices, and lifestyle observations. "
        "Raw transcripts — informal, sometimes incomplete.\n"
    )
    if transcripts:
        current_date = None
        for t in transcripts:
            if t["date"] != current_date:
                current_date = t["date"]
                parts.append(f"\n### {current_date}")
            parts.append(t["raw_text"])
    else:
        parts.append("_No voice notes recorded in this period._\n")

    # Oura data
    parts.append("\n## Oura Ring Biometric Data\n")
    if oura_days:
        for d in oura_days:
            total_h = f"{d['total_sleep_s'] / 3600:.1f}" if d.get("total_sleep_s") else "N/A"
            deep_h = f"{d['deep_sleep_s'] / 3600:.1f}" if d.get("deep_sleep_s") else "?"
            rem_h = f"{d['rem_sleep_s'] / 3600:.1f}" if d.get("rem_sleep_s") else "?"
            light_h = f"{d['light_sleep_s'] / 3600:.1f}" if d.get("light_sleep_s") else "?"

            parts.append(f"### {d['date']}")
            parts.append(f"- Resting HR: {d.get('lowest_heart_rate', 'N/A')} bpm")
            parts.append(f"- Avg HR (sleep): {d.get('average_heart_rate', 'N/A')} bpm")
            parts.append(f"- Avg HRV: {d.get('average_hrv', 'N/A')} ms")
            parts.append(f"- Sleep: {total_h}h (Deep: {deep_h}h, REM: {rem_h}h, Light: {light_h}h)")
            parts.append(f"- Sleep efficiency: {d.get('sleep_efficiency', 'N/A')}%")
            parts.append(f"- Breathing rate: {d.get('breathing_rate', 'N/A')}/min")
            parts.append(f"- Readiness: {d.get('readiness_score', 'N/A')}")
            parts.append(f"- Activity: {d.get('activity_score', 'N/A')} | Steps: {d.get('steps', 'N/A')}")
            parts.append("")
    else:
        parts.append("_No Oura data recorded in this period._\n")

    # Daily checklist data
    parts.append("\n## Daily Checklist (RHR-Influencing Factors)\n")
    if checklists:
        for c in checklists:
            training = c.get("training_type") or "None"
            meal = c.get("last_meal_time") or "-"
            caffeine = c.get("caffeine_cutoff") or "-"
            hydration = (c.get("hydration") or "-").capitalize()
            supps = c.get("supplements") or "None"
            med_min = f" ({c['meditation_minutes']} min)" if c.get("meditation_minutes") else ""

            parts.append(f"### {c['date']}")
            parts.append(f"- Electronics off 1h before bed: {_yn(c.get('electronics_off'))}")
            parts.append(f"- Nasal rinse: {_yn(c.get('nasal_rinse'))}")
            parts.append(f"- Nasal strips: {_yn(c.get('nasal_strips'))}")
            parts.append(f"- Mouth taping: {_yn(c.get('mouth_taping'))}")
            parts.append(f"- Sauna: {_yn(c.get('sauna'))}")
            parts.append(f"- Diaphragm work: {_yn(c.get('diaphragm_work'))}")
            parts.append(f"- Heavy screen/social media day: {_yn(c.get('heavy_screen_day'))}")
            parts.append(f"- Training: {training}")
            parts.append(f"- Last meal: {meal}")
            parts.append(f"- Last caffeine: {caffeine}")
            parts.append(f"- Hydration: {hydration}")
            parts.append(f"- Supplements: {supps}")
            parts.append(f"- Meditation/breathwork: {_yn(c.get('meditation'))}{med_min}")
            parts.append("")
    else:
        parts.append("_No checklist data recorded in this period._\n")

    # Task
    parts.append("## Your Task\n")
    parts.append(
        "Analyze this data and identify:\n"
        "1. **RHR Correlations**: which checklist factors correlate most with lower/higher resting heart rate? "
        "Compare nights where nasal strips, mouth taping, sauna, diaphragm work, etc. were done vs not.\n"
        "2. **Patterns**: recurring correlations between behaviors and biometrics "
        "(e.g., 'on days after X, your HRV tends to be higher')\n"
        "3. **Anomalies**: unusual readings and what might explain them based on the voice notes and checklist\n"
        "4. **Trends**: multi-week trends (improving/declining sleep, HRV, resting HR)\n"
        "5. **Unexpected findings**: anything interesting that wasn't explicitly tracked as a health metric "
        "but seems to correlate with biometric changes\n"
        "6. **Actionable suggestions**: specific, concrete recommendations based on the patterns\n\n"
        "Be specific. Reference actual dates and numbers. Don't hedge with generic health advice."
    )

    return "\n".join(parts)


def run_analysis(api_key: str, db_path: str, model: str, days_back: int = 30) -> str:
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days_back)).isoformat()

    transcripts = get_transcripts(db_path, start, end)
    oura_days = get_oura_data(db_path, start, end)
    checklists = get_checklists(db_path, start, end)

    if not transcripts and not oura_days and not checklists:
        return "No data found for this period. Send some voice notes and pull Oura data first."

    prompt = _build_prompt(transcripts, oura_days, checklists, days_back)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    result = response.content[0].text

    save_analysis(db_path, days_back, prompt, result, model)
    logger.info(f"Analysis complete: {days_back} days, {len(transcripts)} transcripts, {len(oura_days)} oura days")
    return result
