"""Unit tests for GarminMotivationClient with mocked responses."""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from garmin_client import (
    GarminMotivationClient,
    GarminConfig,
    GarminActivity,
    DailySummary,
    WeeklySummary,
)


class TestGarminClient:
    """Test suite with mocked Garmin API responses."""

    @pytest.fixture
    def mock_config(self):
        return GarminConfig(email="test@example.com", password="testpass")

    @pytest.fixture
    def sample_raw_activity(self):
        return {
            "activityId": 123456789,
            "activityName": "Morning Run",
            "activityType": {"typeKey": "running"},
            "startTimeLocal": "2024-01-15T07:30:00Z",
            "duration": 1800,  # 30 min
            "distance": 5000,  # 5 km
            "calories": 350,
            "averageHR": 145,
            "maxHR": 165,
            "trainingStressScore": 45.2,
            "vo2MaxValue": 44.5,
        }

    @pytest.fixture
    def client(self, mock_config):
        with patch("garmin_client.Garmin") as mock_garmin_class:
            mock_garmin = MagicMock()
            mock_garmin_class.return_value = mock_garmin
            client = GarminMotivationClient(mock_config)
            client._client = mock_garmin
            yield client

    @pytest.mark.asyncio
    async def test_normalize_activity(self, client, sample_raw_activity):
        activity = client._normalize_activity(sample_raw_activity)
        assert isinstance(activity, GarminActivity)
        assert activity.activity_id == 123456789
        assert activity.activity_name == "Morning Run"
        assert activity.activity_type == "running"
        assert activity.distance_meters == 5000
        assert activity.duration_seconds == 1800
        assert activity.calories == 350
        assert activity.avg_hr == 145
        assert activity.max_hr == 165

    @pytest.mark.asyncio
    async def test_aggregate_daily_empty(self, client):
        target = date(2024, 1, 15)
        summary = client._aggregate_daily(target, [])
        assert summary.date == target
        assert summary.total_activities == 0
        assert summary.total_distance_km == 0.0

    @pytest.mark.asyncio
    async def test_aggregate_daily_with_activities(self, client, sample_raw_activity):
        target = date(2024, 1, 15)
        activities = [client._normalize_activity(sample_raw_activity)]
        summary = client._aggregate_daily(target, activities)
        assert summary.total_activities == 1
        assert summary.total_distance_km == 5.0
        assert summary.total_duration_min == 30
        assert summary.total_calories == 350
        assert summary.activity_types == {"running": 1}
        assert summary.primary_activity is not None
        assert summary.primary_activity.distance_meters == 5000

    @pytest.mark.asyncio
    async def test_get_current_streak(self, client):
        # Mock get_daily_summary to return activities for 3 consecutive days
        today = date.today()
        call_count = [0]

        async def mock_daily_summary(d):
            call_count[0] += 1
            if call_count[0] <= 3:  # today, yesterday, day before
                return DailySummary(
                    date=d, total_activities=1, total_distance_km=5.0,
                    total_duration_min=30, total_calories=300, activity_types={}
                )
            return DailySummary(
                date=d, total_activities=0, total_distance_km=0.0,
                total_duration_min=0, total_calories=0, activity_types={}
            )

        client.get_daily_summary = mock_daily_summary
        streak = await client.get_current_streak()
        assert streak == 3

    @pytest.mark.asyncio
    async def test_rate_limiting(self, client):
        """Verify rate limiting delay is enforced."""
        import time
        start = time.monotonic()
        await client._respect_rate_limit()
        await client._respect_rate_limit()
        elapsed = time.monotonic() - start
        # Should be at least rate_limit_delay (1.5s)
        assert elapsed >= 1.4  # small tolerance

    @pytest.mark.asyncio
    async def test_retry_on_too_many_requests(self, client):
        from garminconnect import GarminConnectTooManyRequestsError
        call_count = [0]

        def failing_func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise GarminConnectTooManyRequestsError("Rate limited")
            return {"success": True}

        # Should succeed on 3rd attempt
        result = await client._rate_limited_call(failing_func)
        assert result == {"success": True}
        assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_reauth_on_auth_error(self, client):
        from garminconnect import GarminConnectAuthenticationError
        call_count = [0]

        def failing_func():
            call_count[0] += 1
            if call_count[0] == 1:
                raise GarminConnectAuthenticationError("Token expired")
            return {"success": True}

        with patch.object(client, "_ensure_logged_in", new_callable=AsyncMock) as mock_login:
            result = await client._rate_limited_call(failing_func)
            assert result == {"success": True}
            mock_login.assert_called_once()
            assert call_count[0] == 2


class TestModels:
    """Test Pydantic model validation."""

    def test_garmin_activity_validation(self):
        activity = GarminActivity(
            activity_id=1,
            activity_name="Test",
            activity_type="running",
            start_time_local=datetime.now(),
            duration_seconds=1000,
            distance_meters=3000,
            calories=200,
        )
        assert activity.activity_type == "running"
        assert activity.avg_hr is None

    def test_daily_summary_validation(self):
        summary = DailySummary(
            date=date.today(),
            total_activities=2,
            total_distance_km=10.5,
            total_duration_min=60,
            total_calories=500,
            activity_types={"running": 1, "cycling": 1},
        )
        assert summary.total_activities == 2