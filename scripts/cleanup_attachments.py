"""Manual UUID-only orphan cleanup. Defaults to dry-run and 24-hour grace."""
import argparse
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.database import AsyncSessionLocal, engine
from app.helpdesk.attachment_storage import cleanup_orphans

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--grace-hours", type=float, default=24)
    args = parser.parse_args()
    async with AsyncSessionLocal() as db:
        rows = await cleanup_orphans(db, grace_seconds=args.grace_hours * 3600, dry_run=not args.apply)
        print({"dry_run": not args.apply, "objects": rows, "limit": 1000})
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
