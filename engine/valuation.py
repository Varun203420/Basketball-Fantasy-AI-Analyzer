"""Turn game logs into draft values.

Step 1, projections (shared by both formats): each player's per-game stat line
for the coming season is a weighted blend of past seasons (recent season counts
more), shrunk toward a baseline when the sample is small. Projected games played
is a blend of past games played.

Step 2, value:
- Categories: z-score per category against the pool of draftable players.
  FG% and FT% are volume-weighted (a 90% FT shooter on 8 attempts matters more
  than on 1), turnovers count negatively, punted categories are skipped.
- Points: fantasy points per game from the league's point values.
Season VALUE = (per-game value - replacement level) * projected games / 82, so
missing games costs value.

The weights below are starting guesses; tuning them with a backtest is the main
open modeling task (see HANDOFF.md).
"""
import numpy as np
import pandas as pd

from .settings import LOWER_IS_BETTER, LeagueSettings

SEASON_WEIGHTS = [0.7, 0.3]   # most recent season first
GAMES_WEIGHTS = [0.6, 0.4]
SHRINK_GAMES = 15             # games of baseline mixed into small samples
MAX_GAMES = 82

COUNT_STATS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "FGM", "FGA", "FTM", "FTA", "MIN"]
POSITION_MAP = {"G": ["PG", "SG"], "F": ["SF", "PF"], "C": ["C"]}


def project_per_game(logs: pd.DataFrame, seasons: list[str]) -> pd.DataFrame:
    """Projected per-game stats and games for each player. `seasons` most recent first."""
    per_season = logs.groupby(["PLAYER_ID", "SEASON"]).agg(
        PLAYER_NAME=("PLAYER_NAME", "last"),
        TEAM=("TEAM_ABBREVIATION", "last"),
        GP=("GAME_ID", "nunique"),
        **{s: (s, "mean") for s in COUNT_STATS},
    ).reset_index()

    weight_f = dict(zip(seasons, SEASON_WEIGHTS))
    weight_g = dict(zip(seasons, GAMES_WEIGHTS))
    per_season = per_season[per_season["SEASON"].isin(weight_f)].copy()
    per_season["WF"] = per_season["SEASON"].map(weight_f) * per_season["GP"]
    per_season["WG"] = per_season["SEASON"].map(weight_g)

    order = {s: i for i, s in enumerate(seasons)}
    per_season["ORDER"] = per_season["SEASON"].map(order)
    latest = per_season.sort_values("ORDER").groupby("PLAYER_ID").first()[["PLAYER_NAME", "TEAM"]]

    g = per_season.groupby("PLAYER_ID")
    wf = g["WF"].sum()
    proj = pd.DataFrame({s: (per_season[s] * per_season["WF"]).groupby(per_season["PLAYER_ID"]).sum() / wf
                         for s in COUNT_STATS})
    proj["GAMES"] = ((per_season["GP"] * per_season["WG"]).groupby(per_season["PLAYER_ID"]).sum()
                     / g["WG"].sum()).clip(upper=MAX_GAMES)
    proj["SAMPLE"] = wf

    # Shrink small samples toward the median line of regular rotation players.
    rotation = proj[proj["MIN"] >= 15]
    base = rotation[COUNT_STATS].median() if len(rotation) else proj[COUNT_STATS].median()
    k = proj["SAMPLE"] / (proj["SAMPLE"] + SHRINK_GAMES)
    for s in COUNT_STATS:
        proj[s] = proj[s] * k + base[s] * (1 - k)

    proj["FG_PCT"] = proj["FGM"] / proj["FGA"].replace(0, np.nan)
    proj["FT_PCT"] = proj["FTM"] / proj["FTA"].replace(0, np.nan)
    proj = latest.join(proj).reset_index()
    return proj.fillna({"FG_PCT": 0.0, "FT_PCT": 0.0})


def eligible_positions(nba_position) -> str:
    """'G-F' -> 'PG,SG,SF,PF'. Rough mapping; Yahoo eligibility can differ."""
    if not isinstance(nba_position, str) or not nba_position:
        return ""
    slots = []
    for part in nba_position.split("-"):
        for slot in POSITION_MAP.get(part.strip()[:1], []):
            if slot not in slots:
                slots.append(slot)
    return ",".join(slots)


def category_zscores(proj: pd.DataFrame, settings: LeagueSettings) -> pd.DataFrame:
    """Per-game z-score for every category, measured against the draftable pool."""
    cats = settings.categories
    pool_size = min(settings.replacement_rank, len(proj))

    def compute(pool: pd.DataFrame) -> pd.DataFrame:
        z = pd.DataFrame(index=proj.index)
        for cat in cats:
            if cat == "FG_PCT":
                lg = pool["FGM"].sum() / pool["FGA"].sum()
                impact, pool_impact = (proj["FGM"] - lg * proj["FGA"]), (pool["FGM"] - lg * pool["FGA"])
            elif cat == "FT_PCT":
                lg = pool["FTM"].sum() / pool["FTA"].sum()
                impact, pool_impact = (proj["FTM"] - lg * proj["FTA"]), (pool["FTM"] - lg * pool["FTA"])
            else:
                impact, pool_impact = proj[cat], pool[cat]
            std = pool_impact.std() or 1.0
            zc = (impact - pool_impact.mean()) / std
            z["Z_" + cat] = -zc if cat in LOWER_IS_BETTER else zc
        return z

    # Two passes: first against everyone, then against the top of the pool.
    z = compute(proj)
    first_total = z[["Z_" + c for c in settings.active_categories]].sum(axis=1)
    pool = proj.loc[first_total.nlargest(pool_size).index]
    return compute(pool)


def get_player_values(
    logs: pd.DataFrame,
    settings: LeagueSettings,
    seasons: list[str],
    positions: pd.DataFrame | None = None,
    overrides: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Ranked draft values. `seasons` is ordered most recent first.

    `overrides` (optional CSV) has PLAYER_NAME plus any of GAMES, POSITIONS, TEAM
    to hand-correct projections (injuries, trades, Yahoo position eligibility)."""
    proj = project_per_game(logs, seasons)

    if positions is not None and not positions.empty:
        proj = proj.merge(positions, on="PLAYER_ID", how="left")
        proj["POSITIONS"] = proj["NBA_POSITION"].apply(eligible_positions)
        proj = proj.drop(columns=["NBA_POSITION"])
    else:
        proj["POSITIONS"] = ""
    if overrides is not None and not overrides.empty:
        proj = apply_overrides(proj, overrides)

    if settings.scoring_type == "points":
        proj["PER_GAME_VALUE"] = sum(proj[s] * v for s, v in settings.point_values.items())
        proj["FPPG"] = proj["PER_GAME_VALUE"]
    else:
        z = category_zscores(proj, settings)
        proj = proj.join(z)
        proj["PER_GAME_VALUE"] = z[["Z_" + c for c in settings.active_categories]].sum(axis=1)

    proj = proj.sort_values("PER_GAME_VALUE", ascending=False).reset_index(drop=True)
    repl = proj["PER_GAME_VALUE"].iloc[min(settings.replacement_rank, len(proj)) - 1]
    proj["VALUE"] = (proj["PER_GAME_VALUE"] - repl) * proj["GAMES"] / MAX_GAMES
    proj = proj.sort_values("VALUE", ascending=False).reset_index(drop=True)
    proj["RANK"] = range(1, len(proj) + 1)
    return proj


def apply_overrides(proj: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    proj = proj.copy()
    for _, o in overrides.iterrows():
        mask = proj["PLAYER_NAME"].str.lower() == str(o["PLAYER_NAME"]).strip().lower()
        for col in ["GAMES", "POSITIONS", "TEAM"]:
            if col in o and pd.notna(o[col]) and str(o[col]).strip() != "":
                proj.loc[mask, col] = float(o[col]) if col == "GAMES" else str(o[col]).strip()
    return proj
