"""Pull and load NBA data.

Fetching uses nba_api (NBA.com) and must run on a personal machine; NBA.com often
blocks cloud servers. Data is saved to data/ as CSVs so the app never calls NBA.com live.
"""
from pathlib import Path
import time

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

STAT_COLS = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FGM", "FGA", "FG3M", "FTM", "FTA"]


def game_log_path(season: str) -> Path:
    return DATA_DIR / f"game_logs_{season}.csv"


def fetch_game_logs(season: str) -> pd.DataFrame:
    """One row per player per game for a regular season, e.g. season='2025-26'."""
    from nba_api.stats.endpoints import leaguegamelog

    resp = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star="Regular Season",
        player_or_team_abbreviation="P",
        timeout=60,
    )
    df = resp.get_data_frames()[0]
    df["SEASON"] = season
    return df


def fetch_positions() -> pd.DataFrame:
    """NBA.com listed positions (e.g. 'G-F'). Yahoo eligibility can differ; see data/position_overrides.csv."""
    from nba_api.stats.endpoints import playerindex

    df = playerindex.PlayerIndex(timeout=60).get_data_frames()[0]
    return df[["PERSON_ID", "POSITION"]].rename(columns={"PERSON_ID": "PLAYER_ID", "POSITION": "NBA_POSITION"})


def pull(seasons: list[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for season in seasons:
        print(f"Pulling game logs for {season}...")
        df = fetch_game_logs(season)
        df.to_csv(game_log_path(season), index=False)
        print(f"  saved {len(df):,} rows")
        time.sleep(2)  # be gentle with NBA.com
    print("Pulling positions...")
    fetch_positions().to_csv(DATA_DIR / "positions.csv", index=False)
    print("Done.")


def load_game_logs(seasons: list[str]) -> pd.DataFrame:
    frames = [pd.read_csv(game_log_path(s)) for s in seasons if game_log_path(s).exists()]
    if not frames:
        raise FileNotFoundError(f"No game logs in {DATA_DIR}. Run: python scripts/pull_data.py")
    df = pd.concat(frames, ignore_index=True)
    df["MIN"] = df["MIN"].apply(_minutes)
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    return df


def load_positions() -> pd.DataFrame:
    path = DATA_DIR / "positions.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["PLAYER_ID", "NBA_POSITION"])


def _minutes(value) -> float:
    """nba_api returns minutes as a number or 'MM:SS' depending on version."""
    if isinstance(value, str) and ":" in value:
        mins, secs = value.split(":")
        return int(mins) + int(secs) / 60
    return float(value) if pd.notna(value) else 0.0
