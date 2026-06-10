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