"""Pull and load NBA data.

Fetching uses nba_api (NBA.com) and must run on a personal machine; NBA.com often
blocks cloud servers. Data is saved to data/ as CSVs so the app never calls NBA.com live.
"""
from pathlib import Path
import time

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def game_log_path(season: str) -> Path:
    return DATA_DIR / f"game_logs_{season}.csv"


def schedule_path(season: str) -> Path:
    return DATA_DIR / f"schedule_{season}.csv"


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
    """NBA.com listed positions (e.g. 'G-F'). Yahoo eligibility can differ; see data/overrides.csv."""
    from nba_api.stats.endpoints import playerindex

    df = playerindex.PlayerIndex(timeout=60).get_data_frames()[0]
    return df[["PERSON_ID", "POSITION"]].rename(columns={"PERSON_ID": "PLAYER_ID", "POSITION": "NBA_POSITION"})


def fetch_schedule(season: str) -> pd.DataFrame:
    """Every game of the season: date (US Eastern), home and away team abbreviations."""
    from nba_api.stats.endpoints import scheduleleaguev2

    games = scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=60).season_games.get_data_frame()
    out = pd.DataFrame({
        "GAME_ID": games["gameId"],
        "GAME_DATE": pd.to_datetime(games["gameDateEst"]).dt.date,
        "HOME": games["homeTeam_teamTricode"],
        "AWAY": games["awayTeam_teamTricode"],
        "LABEL": games.get("gameLabel", ""),
    })
    # Keep regular-season games between real teams (drops preseason/All-Star/TBD placeholders).
    out = out[out["GAME_ID"].astype(str).str.startswith("002") & out["HOME"].astype(bool) & out["AWAY"].astype(bool)]
    return out.sort_values("GAME_DATE").reset_index(drop=True)


def pull(seasons: list[str], schedule_season: str | None = None, positions: bool = True) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    failures = []

    def step(label, fn):
        print(label)
        try:
            fn()
        except Exception as e:  # keep going so one NBA.com hiccup doesn't lose the rest
            failures.append(label)
            print(f"  FAILED: {e}")
        time.sleep(2)  # be gentle with NBA.com

    for season in seasons:
        def logs(season=season):
            df = fetch_game_logs(season)
            df.to_csv(game_log_path(season), index=False)
            print(f"  saved {len(df):,} rows")
        step(f"Pulling game logs for {season}...", logs)
    if schedule_season:
        def sched():
            df = fetch_schedule(schedule_season)
            df.to_csv(schedule_path(schedule_season), index=False)
            print(f"  saved {len(df):,} games")
        step(f"Pulling schedule for {schedule_season}...", sched)
    if positions:
        step("Pulling positions...", lambda: fetch_positions().to_csv(DATA_DIR / "positions.csv", index=False))
    print("Done." if not failures else f"Done with {len(failures)} failure(s); rerun to retry.")


def load_game_logs(seasons: list[str]) -> pd.DataFrame:
    frames = [pd.read_csv(game_log_path(s)) for s in seasons if game_log_path(s).exists()]
    frames = [f for f in frames if len(f)]
    if not frames:
        raise FileNotFoundError(f"No game logs in {DATA_DIR}. Run: python scripts/pull_data.py")
    df = pd.concat(frames, ignore_index=True)
    df["MIN"] = df["MIN"].apply(_minutes)
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    return df


def load_positions() -> pd.DataFrame:
    path = DATA_DIR / "positions.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["PLAYER_ID", "NBA_POSITION"])


def load_schedule(season: str) -> pd.DataFrame:
    path = schedule_path(season)
    if not path.exists():
        return pd.DataFrame(columns=["GAME_ID", "GAME_DATE", "HOME", "AWAY"])
    df = pd.read_csv(path)
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"]).dt.date
    return df


def data_version(seasons: list[str], season_for_schedule: str) -> tuple:
    """File modification times, so cached results refresh after a new data pull."""
    paths = [game_log_path(s) for s in seasons] + [schedule_path(season_for_schedule), DATA_DIR / "positions.csv",
                                                   DATA_DIR / "overrides.csv"]
    return tuple(p.stat().st_mtime if p.exists() else 0 for p in paths)


def _minutes(value) -> float:
    """nba_api returns minutes as a number or 'MM:SS' depending on version."""
    if isinstance(value, str) and ":" in value:
        mins, secs = value.split(":")
        return int(mins) + int(secs) / 60
    return float(value) if pd.notna(value) else 0.0
