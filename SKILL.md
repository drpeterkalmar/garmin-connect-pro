---
name: garmin-connect-motivation
description: "Use when you want fitness motivation from Garmin Connect data — daily summaries, streak tracking, gentle nudges, and achievement celebrations. Reads activities via garminconnect library with async, type safety, and proper error handling."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [fitness, garmin, motivation, health, async]
    related_skills: []
---

# Garmin Connect Motivation Skill

## Overview

A clean, modern wrapper around the `garminconnect` Python library that fetches your Garmin activity data and turns it into motivational fuel. Designed for async/await, full type safety (Pydantic models), structured error handling, and zero boilerplate.

**Why this skill:** Existing Garmin wrappers (like the ClawHub one) are brittle — sync-only, no types, poor error messages. This skill gives you a robust foundation to build:
- Daily/weekly activity summaries with streaks
- Gentle nudge messages ("You're 2 km from your weekly goal!")
- Achievement celebrations ("First 10k! Longest ride this month!")
- Trend analysis (VO₂ max, resting HR, training load)
- Automated WhatsApp check-ins to "Hermi Status" group

## When to Use

- **Use when:** You want a typed, async Garmin client that doesn't crash on rate limits or token expiry
- **Use when:** Building motivational cron jobs (daily summary at 7 AM, weekly recap Sunday)
- **Use when:** You need structured activity data for dashboards, Notion, Obsidian, etc.
- **Don't use for:** One-off manual CSV exports — use Garmin Connect web UI instead
- **Don't use for:** Real-time live tracking during an activity (use Garmin app)

## Quick Start

```bash
# 1. Install dependency
pip install garminconnect aiohttp pydantic pydantic-settings python-dotenv

# 2. Set env vars (never commit these!)
export GARMIN_EMAIL="your@email.com"
export GARMIN_PASSWORD="your-app-password"  # App-specific password if 2FA enabled
```

## Architecture

```
garmin-connect-motivation/
├── SKILL.md
├── references/
│   └── garmin-api.md          # Endpoint notes, rate limits, data shapes
├── templates/
│   ├── daily_summary.j2       # Jinja2 template for daily motivational message
│   ├── weekly_recap.j2        # Weekly recap template
│   └── streak_celebration.j2  # Streak milestone templates
├── scripts/
│   ├── garmin_client.py       # Typed async client (core)
│   ├── fetch_activities.py    # CLI: fetch last N days, output JSON
│   ├── daily_motivation.py    # CLI: generate today's motivational message
│   └── weekly_recap.py        # CLI: generate weekly recap
└── tests/
    └── test_garmin_client.py  # Unit tests with mocked responses
```

## Core Module: `scripts/garmin_client.py`

```python
"""Async, typed Garmin Connect client with automatic token refresh and retries."""

from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from pathlib import Path
from pydantic import BaseModel
from garminconnect import Garmin
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

# Load .env file from skill directory
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


# ---- Pydantic Models (type-safe API) ----

class GarminActivity(BaseModel):
    """Normalized activity — only fields we actually use."""
    activity_id: int
    activity_name: str
    activity_type: str  # running, cycling, swimming, strength_training, etc.
    start_time_local: datetime
    duration_seconds: int
    distance_meters: float
    calories: int
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    training_stress_score: Optional[float] = None  # TSS / Training Load
    vo2_max_value: Optional[float] = None


class DailySummary(BaseModel):
    """Aggregated daily metrics for motivation."""
    date: date
    total_activities: int
    total_distance_km: float
    total_duration_min: int
    total_calories: int
    activity_types: dict[str, int]  # {"running": 2, "cycling": 1}
    primary_activity: Optional[GarminActivity] = None  # longest/most intense


class WeeklySummary(BaseModel):
    """Aggregated weekly metrics with streak tracking."""
    week_start: date
    week_end: date
    total_activities: int
    total_distance_km: float
    total_duration_hours: float
    total_calories: int
    active_days: int
    current_streak_days: int
    longest_streak_days: int
    avg_vo2_max: Optional[float] = None
    avg_resting_hr: Optional[int] = None


# ---- Client ----

@dataclass
class GarminConfig:
    email: str = field(default_factory=lambda: os.getenv("GARMIN_EMAIL", ""))
    password: str = field(default_factory=lambda: os.getenv("GARMIN_PASSWORD", ""))
    rate_limit_delay: float = 1.5  # seconds between requests
    max_retries: int = 3
    timeout_seconds: int = 30


class GarminMotivationClient:
    """High-level async client for motivational data fetching."""

    def __init__(self, config: Optional[GarminConfig] = None):
        self.config = config or GarminConfig()
        if not self.config.email or not self.config.password:
            raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD must be set")
        self._client: Optional[Garmin] = None
        self._last_request: float = 0.0

    async def __aenter__(self) -> "GarminMotivationClient":
        await self._ensure_logged_in()
        return self

    async def __aexit__(self, *args):
        # garminconnect doesn't have async close; session cleanup is automatic
        pass

    async def _ensure_logged_in(self) -> None:
        """Login with automatic retry on token expiry."""
        if self._client is not None:
            return
        loop = asyncio.get_event_loop()
        self._client = await loop.run_in_executor(None, self._sync_login)

    def _sync_login(self) -> Garmin:
        """Blocking login — runs in executor."""
        client = Garmin(self.config.email, self.config.password)
        client.login()
        return client

    async def _rate_limited_call(self, func, *args, **kwargs):
        """Execute sync garminconnect call with rate limiting + retries."""
        await self._respect_rate_limit()
        loop = asyncio.get_event_loop()
        for attempt in range(self.config.max_retries):
            try:
                return await loop.run_in_executor(None, func, *args, **kwargs)
            except GarminConnectTooManyRequestsError:
                if attempt == self.config.max_retries - 1:
                    raise
                wait = (2 ** attempt) * 5  # 5s, 10s, 20s backoff
                await asyncio.sleep(wait)
            except GarminConnectAuthenticationError:
                # Token expired — force re-login
                self._client = None
                await self._ensure_logged_in()
                # Retry once after re-login
                if attempt == self.config.max_retries - 1:
                    raise
                continue
            except GarminConnectConnectionError as e:
                if attempt == self.config.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Max retries exceeded")

    async def _respect_rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        import time
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self.config.rate_limit_delay:
            await asyncio.sleep(self.config.rate_limit_delay - elapsed)
        self._last_request = time.monotonic()

    # ---- Public API ----

    async def get_activities(self, start_date: date, end_date: Optional[date] = None, limit: int = 100) -> list[GarminActivity]:
        """Fetch activities in date range, normalized to Pydantic models."""
        end_date = end_date or date.today()
        raw = await self._rate_limited_call(
            self._client.get_activities_by_date,
            start_date.isoformat(),
            end_date.isoformat()
        )
        return [self._normalize_activity(a) for a in raw]

    async def get_daily_summary(self, target_date: date) -> DailySummary:
        """Aggregated summary for a single day."""
        activities = await self.get_activities(target_date, target_date)
        return self._aggregate_daily(target_date, activities)

    async def get_weekly_summary(self, week_start: date) -> WeeklySummary:
        """Aggregated summary for a week (Mon-Sun), including streak calculation."""
        week_end = week_start + timedelta(days=6)
        activities = await self.get_activities(week_start, week_end)
        return self._aggregate_weekly(week_start, week_end, activities)

    async def get_current_streak(self) -> int:
        """Calculate current consecutive active days streak (backwards from today)."""
        today = date.today()
        streak = 0
        check_date = today
        while True:
            summary = await self.get_daily_summary(check_date)
            if summary.total_activities > 0:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break
            if streak > 365:  # sanity cap
                break
        return streak

    async def get_vo2_max_trend(self, days: int = 30) -> list[tuple[date, float]]:
        """VO₂ max trend over N days (requires Garmin Connect Premium)."""
        end = date.today()
        start = end - timedelta(days=days)
        raw = await self._rate_limited_call(self._client.get_vo2_max, start.isoformat(), end.isoformat())
        return [(datetime.fromisoformat(d["date"]).date(), d["vo2MaxValue"]) for d in raw if d.get("vo2MaxValue")]

    async def get_resting_hr_trend(self, days: int = 30) -> list[tuple[date, int]]:
        """Resting heart rate trend over N days."""
        end = date.today()
        start = end - timedelta(days=days)
        raw = await self._rate_limited_call(self._client.get_resting_heart_rate, start.isoformat(), end.isoformat())
        return [(datetime.fromisoformat(d["date"]).date(), d["restingHeartRate"]) for d in raw if d.get("restingHeartRate")]

    # ---- Normalization / Aggregation ----

    def _normalize_activity(self, raw: dict) -> GarminActivity:
        """Convert raw Garmin dict to typed model."""
        return GarminActivity(
            activity_id=raw["activityId"],
            activity_name=raw.get("activityName", "Unnamed"),
            activity_type=raw.get("activityType", {}).get("typeKey", "unknown"),
            start_time_local=datetime.fromisoformat(raw["startTimeLocal"].replace("Z", "+00:00")),
            duration_seconds=int(raw["duration"]),
            distance_meters=raw.get("distance", 0),
            calories=raw.get("calories", 0),
            avg_hr=raw.get("averageHR"),
            max_hr=raw.get("maxHR"),
            training_stress_score=raw.get("trainingStressScore"),
            vo2_max_value=raw.get("vo2MaxValue"),
        )

    def _aggregate_daily(self, target_date: date, activities: list[GarminActivity]) -> DailySummary:
        if not activities:
            return DailySummary(
                date=target_date,
                total_activities=0,
                total_distance_km=0.0,
                total_duration_min=0,
                total_calories=0,
                activity_types={},
            )
        types: dict[str, int] = {}
        for a in activities:
            types[a.activity_type] = types.get(a.activity_type, 0) + 1
        primary = max(activities, key=lambda a: a.distance_meters)
        return DailySummary(
            date=target_date,
            total_activities=len(activities),
            total_distance_km=sum(a.distance_meters for a in activities) / 1000,
            total_duration_min=sum(a.duration_seconds for a in activities) // 60,
            total_calories=sum(a.calories for a in activities),
            activity_types=types,
            primary_activity=primary,
        )

    def _aggregate_weekly(self, week_start: date, week_end: date, activities: list[GarminActivity]) -> WeeklySummary:
        if not activities:
            return WeeklySummary(
                week_start=week_start,
                week_end=week_end,
                total_activities=0,
                total_distance_km=0.0,
                total_duration_hours=0.0,
                total_calories=0,
                active_days=0,
                current_streak_days=0,  # Will be filled by caller if needed
                longest_streak_days=0,
            )
        # Active days in this week
        active_days_set = {a.start_time_local.date() for a in activities}
        return WeeklySummary(
            week_start=week_start,
            week_end=week_end,
            total_activities=len(activities),
            total_distance_km=sum(a.distance_meters for a in activities) / 1000,
            total_duration_hours=sum(a.duration_seconds for a in activities) / 3600,
            total_calories=sum(a.calories for a in activities),
            active_days=len(active_days_set),
            current_streak_days=0,  # Will be filled by caller
            longest_streak_days=0,  # Would need historical scan
        )
```

## CLI Scripts

### `scripts/fetch_activities.py`
```python
#!/usr/bin/env python3
"""Fetch last N days of activities → JSON (for piping to other tools)."""
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from garmin_client import GarminMotivationClient


async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    end = date.today()
    start = end - timedelta(days=days)
    async with GarminMotivationClient() as client:
        activities = await client.get_activities(start, end)
    print(json.dumps([a.model_dump(mode="json") for a in activities], indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
```

### `scripts/daily_motivation.py`
```python
#!/usr/bin/env python3
"""Generate today's motivational message → stdout (for cron + WhatsApp)."""
import asyncio
import sys
from datetime import date
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent))
from garmin_client import GarminMotivationClient, DailySummary

TEMPLATES = Path(__file__).parent.parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=False)

MOTIVATIONAL_TEMPLATE = env.get_template("daily_summary.j2")


async def main():
    target = date.today()
    async with GarminMotivationClient() as client:
        summary: DailySummary = await client.get_daily_summary(target)
        streak = await client.get_current_streak()
    print(MOTIVATIONAL_TEMPLATE.render(summary=summary, streak=streak, date=target))


if __name__ == "__main__":
    asyncio.run(main())
```

### `scripts/weekly_recap.py`
```python
#!/usr/bin/env python3
"""Generate weekly recap (Mon-Sun) → stdout."""
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, str(Path(__file__).parent))
from garmin_client import GarminMotivationClient, WeeklySummary

TEMPLATES = Path(__file__).parent.parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=False)
WEEKLY_TEMPLATE = env.get_template("weekly_recap.j2")


async def main():
    today = date.today()
    # Monday of this week
    week_start = today - timedelta(days=today.weekday())
    async with GarminMotivationClient() as client:
        summary: WeeklySummary = await client.get_weekly_summary(week_start)
        streak = await client.get_current_streak()
    print(WEEKLY_TEMPLATE.render(summary=summary, streak=streak))


if __name__ == "__main__":
    asyncio.run(main())
```

## Templates (Jinja2)

### `templates/daily_summary.j2`
```
🏃‍♂️ **Daily Movement — {{ date.strftime("%A, %d. %B") }}**

{% if summary.total_activities == 0 %}
😴 Ruhetag — morgen geht's weiter! 
   Aktueller Streak: {{ streak }} Tag{% if streak != 1 %}e{% endif %} 🔥
{% else %}
✅ {{ summary.total_activities }} Aktivität{% if summary.total_activities != 1 %}en{% endif %}
📏 {{ "%.1f"|format(summary.total_distance_km) }} km  •  ⏱ {{ summary.total_duration_min }} min  •  🔥 {{ summary.total_calories }} kcal
{% for type, count in summary.activity_types.items() %}
   • {{ type|title }}: {{ count }}
{% endfor %}
{% if summary.primary_activity %}
🏆 Highlight: {{ summary.primary_activity.activity_name }} ({{ "%.1f"|format(summary.primary_activity.distance_meters/1000) }} km)
{% endif %}
🔥 **Streak: {{ streak }} Tag{% if streak != 1 %}e{% endif %}** — weiter so!
{% endif %}
```

### `templates/weekly_recap.j2`
```
📊 **Wochen-Rückblick — KW {{ summary.week_start.isocalendar()[1] }} ({{ summary.week_start.strftime("%d.%m.")}}–{{ summary.week_end.strftime("%d.%m.")}})**

{% if summary.total_activities == 0 %}
Diese Woche war ruhig. Nächste Woche rocken wir's! 💪
{% else %}
✅ {{ summary.total_activities }} Aktivitäten
📏 {{ "%.1f"|format(summary.total_distance_km) }} km total
⏱ {{ "%.1f"|format(summary.total_duration_hours) }} Std. Bewegung
🔥 {{ summary.total_calories }} kcal verbrannt
📅 {{ summary.active_days }}/7 aktive Tage
🔥 **Streak: {{ streak }} Tage** {% if streak >= 7 %}🔥{% elif streak >= 3 %}⭐{% endif %}
{% endif %}
```

### `templates/streak_celebration.j2`
```
{% if streak == 3 %}🎉 **3-Tage-Streak!** Der Anfang ist gemacht!
{% elif streak == 7 %}🔥 **Eine Woche am Ball!** Disziplin zahlt sich aus.
{% elif streak == 14 %}💪 **Zwei Wochen!** Das ist schon Routine.
{% elif streak == 30 %}🏆 **30 Tage!** Ein Monat Konsistenz — Respekt!
{% elif streak % 7 == 0 and streak >= 21 %}🌟 **{{ streak }} Tage!** {{ streak//7 }} Wochen durchgezogen.
{% endif %}
```

## Cron Job Integration (Hermes)

```bash
# Daily motivation at 7:00 AM → WhatsApp "Hermi Status" group
hermes cronjob create \
  --name "garmin-daily-motivation" \
  --schedule "0 7 * * *" \
  --prompt "Run ~/.hermes/skills/leisure/garmin-connect-motivation/scripts/daily_motivation.py and send output to WhatsApp group 'Hermi Status'" \
  --skills "garmin-connect-motivation"

# Weekly recap Sunday 10:00 AM
hermes cronjob create \
  --name "garmin-weekly-recap" \
  --schedule "0 10 * * 0" \
  --prompt "Run ~/.hermes/skills/leisure/garmin-connect-motivation/scripts/weekly_recap.py and send output to WhatsApp group 'Hermi Status'" \
  --skills "garmin-connect-motivation"
```

## Common Pitfalls

1. **2FA / App Password:** Garmin requires an app-specific password if you have 2FA enabled. Generate at `garmin.com/settings/security/apppasswords`.
2. **Rate Limits:** Garmin allows ~30 req/min. The client enforces 1.5s delay + exponential backoff — don't lower it.
3. **Token Expiry:** Sessions last ~30 min. Client auto-re-auths on `GarminConnectAuthenticationError`.
4. **Timezones:** `startTimeLocal` is local to the activity. `date.today()` uses system timezone — ensure Mac mini is on your local TZ.
5. **Missing VO₂ Max / Resting HR:** Requires Garmin Connect Premium + compatible device. Handle `None` gracefully.
6. **First Run:** Test with `python scripts/fetch_activities.py 1` before wiring cron.
7. **Dataclass + Pydantic Field:** Don't use `pydantic.Field` in `@dataclass` — use `dataclasses.field(default_factory=...)`.
8. **Garmin `duration` is Float:** Cast to `int` in normalization (`int(raw["duration"])`).
9. **`get_activities_by_date` Signature:** No `limit` param — pagination is internal. Pass only `startdate`, `enddate`.
10. **`.env` Load Order:** Call `load_dotenv()` at module top-level, before any class that reads `os.getenv()`.

## References

- `references/debugging-session-2026-06-10.md` — Full debug log from initial creation
- `references/cron-setup.md` — Cron job commands for daily/weekly WhatsApp delivery
- `references/signal-delivery-setup.md` — Signal delivery configuration for cron jobs

## Verification Checklist

- [ ] `GARMIN_EMAIL` and `GARMIN_PASSWORD` (app password) set in env
- [ ] `pip install garminconnect aiohttp pydantic pydantic-settings python-dotenv jinja2`
- [ ] `python scripts/fetch_activities.py 1` returns valid JSON
- [ ] `python scripts/daily_motivation.py` renders a nice message
- [ ] `python scripts/weekly_recap.py` renders weekly summary
- [ ] Cron jobs created and deliver to "Hermi Status" WhatsApp group
- [ ] Streak calculation works (test by checking yesterday's activity)

## One-Shot Recipes

### "Give me this week's data as JSON for my Notion dashboard"
```bash
python ~/.hermes/skills/leisure/garmin-connect-motivation/scripts/fetch_activities.py 7 > week.json
```

### "Test the daily message right now"
```bash
cd ~/.hermes/skills/leisure/garmin-connect-motivation && python scripts/daily_motivation.py
```

### "Check current streak without full summary"
```python
async with GarminMotivationClient() as c:
    print(await c.get_current_streak())
```