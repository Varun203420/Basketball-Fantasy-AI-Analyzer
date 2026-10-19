"""Download NBA game logs, the schedule, and positions into data/. Run on your own laptop.

    python scripts/pull_data.py              # everything (first time)
    python scripts/pull_data.py --daily      # just this season's games + schedule (fast; run daily)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.data import pull  # noqa: E402
from engine.settings import ALL_SEASONS, CURRENT_SEASON  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", nargs="+", default=None, help="seasons to pull, e.g. 2025-26 2024-25")
    parser.add_argument("--daily", action="store_true", help=f"only refresh {CURRENT_SEASON} games and schedule")
    args = parser.parse_args()
    if args.daily:
        pull([CURRENT_SEASON], schedule_season=CURRENT_SEASON, positions=False)
    else:
        pull(args.seasons or ALL_SEASONS, schedule_season=CURRENT_SEASON)
