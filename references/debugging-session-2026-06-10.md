# Garmin Connect Motivation — Debugging Session (2026-06-10)

## Summary
Created the `garmin-connect-motivation` skill from scratch. Encountered and fixed several issues during initial test runs.

## Issues Fixed

### 1. Dataclass + Pydantic Field Mismatch
**Error:** `Config email: FieldInfo(...)` — Pydantic `Field()` doesn't work in `@dataclass`.
**Fix:** Use `dataclasses.field(default_factory=...)` instead.
```python
# WRONG
from pydantic import Field
@dataclass
class GarminConfig:
    email: str = Field(default_factory=lambda: os.getenv("GARMIN_EMAIL", ""))

# CORRECT
from dataclasses import dataclass, field
@dataclass
class GarminConfig:
    email: str = field(default_factory=lambda: os.getenv("GARMIN_EMAIL", ""))
```

### 2. `duration` Field is Float, Not Int
**Error:** Pydantic validation error: `duration_seconds: Input should be a valid integer, got a number with a fractional part [type=int_from_float, input_value=2921.333...]`
**Fix:** Cast to `int` in `_normalize_activity`:
```python
duration_seconds=int(raw["duration"]),
```

### 3. `get_activities_by_date` Signature
**Error:** `API Error 400 - Activity type specified is invalid` when passing `limit` as 3rd positional arg.
**Root cause:** Method signature is `(self, startdate, enddate=None, activitytype=None, sortorder=None)` — no `limit` param. Pagination is internal.
**Fix:** Call with only `start_date.isoformat(), end_date.isoformat()`.

### 4. `.env` Load Order
**Problem:** `GarminConfig` reads `os.getenv()` at class definition time, but `load_dotenv()` was called after class definition.
**Fix:** Call `load_dotenv()` at module top-level, before any class that uses `os.getenv()`:
```python
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent.parent / ".env")

@dataclass
class GarminConfig:
    email: str = field(default_factory=lambda: os.getenv("GARMIN_EMAIL", ""))
    ...
```

### 5. Signal Delivery Cron Jobs
Created two cron jobs delivering to **Signal** (not WhatsApp):
- `garmin-daily` — Daily 07:00 → `daily_motivation.py`
- `garmin-weekly` — Sunday 10:00 → `weekly_recap.py`
Both with `deliver: "signal"` in cron definition.

## Test Results
```
fetch_activities.py 1  →  2 Activities (Crosstrainer + Krafttraining, 9. Juni)
daily_motivation.py    →  Ruhetag-Message (Streak: 0)
weekly_recap.py        →  KW 24: 2 Aktivitäten, 1.3h, 595 kcal
pytest tests/          →  9 passed
```

## Files Created
```
~/.hermes/skills/leisure/garmin-connect-motivation/
├── SKILL.md
├── requirements.txt
├── .env.example
├── .env (with real credentials)
├── scripts/
│   ├── garmin_client.py
│   ├── fetch_activities.py
│   ├── daily_motivation.py
│   └── weekly_recap.py
├── templates/
│   ├── daily_summary.j2
│   ├── weekly_recap.j2
│   └── streak_celebration.j2
├── tests/
│   └── test_garmin_client.py
└── references/
    ├── signal-delivery-setup.md (this session)
    └── debugging-session-2026-06-10.md (this file)
```