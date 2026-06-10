"""Async, typed Garmin Connect client with automatic token refresh and retries."""

from __future__ import annotations
import asyncio
import os
from dataclasses import dataclass, field
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