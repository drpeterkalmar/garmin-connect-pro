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