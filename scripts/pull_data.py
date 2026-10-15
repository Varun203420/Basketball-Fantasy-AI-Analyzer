"""Download NBA game logs and positions into data/. Run on your own laptop:

    python scripts/pull_data.py
    python scripts/pull_data.py --seasons 2025-26 2024-25
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.data import pull  # noqa: E402

DEFAULT_SEASONS = ["2025-26", "2024-25"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS)
    pull(parser.parse_args().seasons)
