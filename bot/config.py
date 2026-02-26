import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str
    anthropic_api_key: str
    oura_personal_token: str
    db_path: str = "data/health.db"
    oura_pull_hour: int = 14
    checklist_reminder_hour: int = 20
    checklist_reminder_minute: int = 50
    analysis_model: str = "claude-sonnet-4-20250514"
    whisper_model: str = "whisper-1"


def load_settings() -> Settings:
    load_dotenv()
    db_path = os.environ.get("DB_PATH", "data/health.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        oura_personal_token=os.environ["OURA_PERSONAL_TOKEN"],
        db_path=db_path,
        oura_pull_hour=int(os.environ.get("OURA_PULL_HOUR", "14")),
        checklist_reminder_hour=int(os.environ.get("CHECKLIST_REMINDER_HOUR", "20")),
        checklist_reminder_minute=int(os.environ.get("CHECKLIST_REMINDER_MINUTE", "50")),
    )
