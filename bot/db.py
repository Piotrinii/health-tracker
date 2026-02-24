import json
import sqlite3
from datetime import date, datetime


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str) -> None:
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            date        TEXT NOT NULL,
            raw_text    TEXT NOT NULL,
            duration_s  REAL,
            file_id     TEXT
        );

        CREATE TABLE IF NOT EXISTS oura_data (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT NOT NULL UNIQUE,
            fetched_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            lowest_heart_rate   INTEGER,
            average_heart_rate  INTEGER,
            average_hrv         INTEGER,
            total_sleep_s       INTEGER,
            rem_sleep_s         INTEGER,
            deep_sleep_s        INTEGER,
            light_sleep_s       INTEGER,
            sleep_efficiency    INTEGER,
            breathing_rate      REAL,
            readiness_score     INTEGER,
            activity_score      INTEGER,
            steps               INTEGER,
            raw_sleep_json      TEXT,
            raw_readiness_json  TEXT,
            raw_activity_json   TEXT
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            days_back   INTEGER NOT NULL,
            prompt      TEXT NOT NULL,
            response    TEXT NOT NULL,
            model       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_checklist (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT NOT NULL UNIQUE,
            created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
            electronics_off     INTEGER,  -- 1=yes 0=no
            nasal_rinse         INTEGER,
            nasal_strips        INTEGER,
            mouth_taping        INTEGER,
            sauna               INTEGER,
            diaphragm_work      INTEGER,
            heavy_screen_day    INTEGER,
            meditation          INTEGER,
            meditation_minutes  INTEGER,
            training_type       TEXT,     -- NULL=no training, else type string
            last_meal_time      TEXT,     -- HH:MM
            caffeine_cutoff     TEXT,     -- HH:MM
            hydration           TEXT,     -- 'good' or 'poor'
            supplements         TEXT,     -- free text, NULL=none
            other_notes         TEXT      -- JSON dict of "other" answers, NULL=none
        );

        CREATE TABLE IF NOT EXISTS last_meal_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL UNIQUE,
            time        TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
        );

        CREATE INDEX IF NOT EXISTS idx_transcripts_date ON transcripts(date);
        CREATE INDEX IF NOT EXISTS idx_oura_date ON oura_data(date);
        CREATE INDEX IF NOT EXISTS idx_checklist_date ON daily_checklist(date);
    """)
    conn.close()


def save_transcript(db_path: str, day: str, raw_text: str, duration_s: float | None = None, file_id: str | None = None) -> int:
    conn = get_connection(db_path)
    cur = conn.execute(
        "INSERT INTO transcripts (date, raw_text, duration_s, file_id) VALUES (?, ?, ?, ?)",
        (day, raw_text, duration_s, file_id),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def save_oura_data(db_path: str, day: str, sleep: dict | None, readiness: dict | None, activity: dict | None) -> None:
    s = sleep or {}
    r = readiness or {}
    a = activity or {}

    conn = get_connection(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO oura_data
           (date, lowest_heart_rate, average_heart_rate, average_hrv,
            total_sleep_s, rem_sleep_s, deep_sleep_s, light_sleep_s,
            sleep_efficiency, breathing_rate, readiness_score,
            activity_score, steps, raw_sleep_json, raw_readiness_json, raw_activity_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            day,
            s.get("lowest_heart_rate"),
            s.get("average_heart_rate"),
            s.get("average_hrv"),
            s.get("total_sleep_duration"),
            s.get("rem_sleep_duration"),
            s.get("deep_sleep_duration"),
            s.get("light_sleep_duration"),
            s.get("efficiency"),
            s.get("average_breath"),
            r.get("score"),
            a.get("score"),
            a.get("steps"),
            json.dumps(sleep) if sleep else None,
            json.dumps(readiness) if readiness else None,
            json.dumps(activity) if activity else None,
        ),
    )
    conn.commit()
    conn.close()


def get_transcripts(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT date, raw_text, duration_s FROM transcripts WHERE date >= ? AND date <= ? ORDER BY date, created_at",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_oura_data(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM oura_data WHERE date >= ? AND date <= ? ORDER BY date",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_analysis(db_path: str, days_back: int, prompt: str, response: str, model: str) -> int:
    conn = get_connection(db_path)
    cur = conn.execute(
        "INSERT INTO analyses (days_back, prompt, response, model) VALUES (?, ?, ?, ?)",
        (days_back, prompt, response, model),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def save_checklist(db_path: str, day: str, data: dict) -> None:
    conn = get_connection(db_path)
    other_notes = data.get("other_notes")
    other_notes_json = json.dumps(other_notes) if other_notes else None
    conn.execute(
        """INSERT OR REPLACE INTO daily_checklist
           (date, electronics_off, nasal_rinse, nasal_strips, mouth_taping,
            sauna, diaphragm_work, heavy_screen_day, meditation, meditation_minutes,
            training_type, last_meal_time, caffeine_cutoff, hydration, supplements,
            other_notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            day,
            data.get("electronics_off"),
            data.get("nasal_rinse"),
            data.get("nasal_strips"),
            data.get("mouth_taping"),
            data.get("sauna"),
            data.get("diaphragm_work"),
            data.get("heavy_screen_day"),
            data.get("meditation"),
            data.get("meditation_minutes"),
            data.get("training_type"),
            data.get("last_meal_time"),
            data.get("caffeine_cutoff"),
            data.get("hydration"),
            data.get("supplements"),
            other_notes_json,
        ),
    )
    conn.commit()
    conn.close()


def get_checklists(db_path: str, start: str, end: str) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM daily_checklist WHERE date >= ? AND date <= ? ORDER BY date",
        (start, end),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_setting(db_path: str, key: str) -> str | None:
    conn = get_connection(db_path)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(db_path: str, key: str, value: str) -> None:
    conn = get_connection(db_path)
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def save_last_meal_time(db_path: str, day: str, time_str: str) -> None:
    conn = get_connection(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO last_meal_log (date, time) VALUES (?, ?)",
        (day, time_str),
    )
    conn.commit()
    conn.close()


def get_last_meal_time(db_path: str, day: str) -> str | None:
    conn = get_connection(db_path)
    row = conn.execute("SELECT time FROM last_meal_log WHERE date = ?", (day,)).fetchone()
    conn.close()
    return row["time"] if row else None


def get_stats(db_path: str) -> dict:
    conn = get_connection(db_path)
    transcript_count = conn.execute("SELECT COUNT(*) as c FROM transcripts").fetchone()["c"]
    oura_count = conn.execute("SELECT COUNT(*) as c FROM oura_data").fetchone()["c"]
    last_analysis = conn.execute("SELECT created_at FROM analyses ORDER BY id DESC LIMIT 1").fetchone()
    last_transcript = conn.execute("SELECT date FROM transcripts ORDER BY date DESC LIMIT 1").fetchone()
    last_oura = conn.execute("SELECT date FROM oura_data ORDER BY date DESC LIMIT 1").fetchone()
    first_transcript = conn.execute("SELECT date FROM transcripts ORDER BY date ASC LIMIT 1").fetchone()
    first_oura = conn.execute("SELECT date FROM oura_data ORDER BY date ASC LIMIT 1").fetchone()
    first_checklist = conn.execute("SELECT date FROM daily_checklist ORDER BY date ASC LIMIT 1").fetchone()
    conn.close()

    # Earliest date across all data sources
    earliest_dates = [d["date"] for d in [first_transcript, first_oura, first_checklist] if d]
    earliest = min(earliest_dates) if earliest_dates else None

    return {
        "transcript_count": transcript_count,
        "oura_count": oura_count,
        "last_analysis": last_analysis["created_at"] if last_analysis else None,
        "last_transcript_date": last_transcript["date"] if last_transcript else None,
        "last_oura_date": last_oura["date"] if last_oura else None,
        "earliest_date": earliest,
    }
