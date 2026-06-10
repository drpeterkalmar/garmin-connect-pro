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