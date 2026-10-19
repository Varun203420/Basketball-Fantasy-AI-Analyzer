"""Turn game logs into player values.

Step 1, projections: each player's per-game line is a blend of recent seasons.
Each season counts in proportion to (season weight x games played), so a few
early games of the current season barely move the projection, and by midseason
they carry real weight. Small samples are shrunk lightly toward a typical
rotation player. Projected games come from completed seasons only, regressed
toward a normal season so one injury year doesn't sink a star.

Step 2, value:
- Categories: per-game z-score in each category against the draftable pool.
  FG% and FT% are volume-weighted (a 90% FT shooter on 8 attempts matters more
  than on 1); turnovers count negatively; punted categories are skipped.
- Points: fantasy points per game from the league's point values.
PER_GAME_VALUE is the sum; VALUE is (per-game value - replacement level), scaled
for availability by settings.availability_weight.

Weights are reasonable starting points, not tuned; backtesting them is open
modeling work (see HANDOFF.md).
"""
import numpy as np
import pandas as pd

from .settings import ALL_SEASONS, CURRENT_SEASON, LOWER_IS_BETTER, LeagueSettings

SEASON_WEIGHTS = {0: 1.0, 1: 0.6, 2: 0.3}  # by recency: newest season present = 0
GAMES_WEIGHTS = [0.6, 0.4]                # completed seasons, most recent first
TYPICAL_GAMES = 70                        # games regressed toward this
GAMES_REGRESSION = 0.3                    # share of the projection that is TYPICAL_GAMES
SHRINK_GAMES = 8                          # games of "typical player" mixed into each line
MAX_GAMES = 82

COUNT_STATS = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV", "FGM", "FGA", "FTM", "FTA", "MIN"]
POSITION_MAP = {"G": ["PG", "SG"], "F": ["SF", "PF"], "C": ["C"]}


def project_per_game(logs: pd.DataFrame, seasons: list[str] | None = None) -> pd.DataFrame:
    """Projected per-game stats and games for each player. `seasons` most recent first."""
    seasons = [s for s in (seasons or ALL_SEASONS) if s in set(logs["SEASON"])]
    per_season = logs[logs["SEASON"].isin(seasons)].groupby(["PLAYER_ID", "SEASON"]).agg(
        PLAYER_NAME=("PLAYER_NAME", "last"),
        TEAM=("TEAM_ABBREVIATION", "last"),
        LAST_DATE=("GAME_DATE", "max"),
        GP=("GAME_ID", "nunique"),
        **{s: (s, "mean") for s in COUNT_STATS},
    ).reset_index()

    recency = {s: i for i, s in enumerate(seasons)}
    per_season["W"] = per_season["SEASON"].map(recency).map(SEASON_WEIGHTS).fillna(0.0) * per_season["GP"]
    pid = per_season["PLAYER_ID"]

    # Name and team from each player's most recent game.
    latest = per_season.sort_values("LAST_DATE").groupby("PLAYER_ID").last()[["PLAYER_NAME", "TEAM"]]

    w = per_season["W"].groupby(pid).sum().replace(0, np.nan)
    proj = pd.DataFrame({s: (per_season[s] * per_season["W"]).groupby(pid).sum() / w for s in COUNT_STATS})
    total_gp = per_season["GP"].groupby(pid).sum()

    # Light shrinkage toward the median rotation player; matters only for small samples.
    rotation = proj[proj["MIN"] >= 20]
    base = (rotation if len(rotation) else proj)[COUNT_STATS].median()
    k = total_gp / (total_gp + SHRINK_GAMES)
    for s in COUNT_STATS:
        proj[s] = proj[s] * k + base[s] * (1 - k)

    # Projected games: completed seasons only, regressed toward a normal season.
    completed = [s for s in seasons if s != CURRENT_SEASON]
    gp_by_season = per_season.pivot_table(index="PLAYER_ID", columns="SEASON", values="GP")
    num = pd.Series(0.0, index=proj.index)
    den = pd.Series(0.0, index=proj.index)
    for season, wt in zip(completed, GAMES_WEIGHTS):
        if season in gp_by_season:
            gp = gp_by_season[season].reindex(proj.index)
            num += gp.fillna(0) * wt
            den += gp.notna() * wt
    hist_games = (num / den.replace(0, np.nan)).fillna(TYPICAL_GAMES)
    proj["GAMES"] = ((1 - GAMES_REGRESSION) * hist_games + GAMES_REGRESSION * TYPICAL_GAMES).clip(upper=MAX_GAMES)
    proj["GP_TOTAL"] = total_gp
    for season in seasons:
        proj["GP_" + season] = gp_by_season[season].reindex(proj.index).fillna(0).astype(int) \
            if season in gp_by_season else 0

    proj["FG_PCT"] = (proj["FGM"] / proj["FGA"].replace(0, np.nan)).fillna(0.0)
    proj["FT_PCT"] = (proj["FTM"] / proj["FTA"].replace(0, np.nan)).fillna(0.0)
    return latest.join(proj).reset_index()


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


def category_params(pool: pd.DataFrame, settings: LeagueSettings) -> dict:
    """Mean/std (and league % for FG/FT) of each category's per-game impact in a pool."""
    params = {}
    for cat in settings.categories:
        lg = None
        if cat == "FG_PCT":
            lg = pool["FGM"].sum() / pool["FGA"].sum()
            impact = pool["FGM"] - lg * pool["FGA"]
        elif cat == "FT_PCT":
            lg = pool["FTM"].sum() / pool["FTA"].sum()
            impact = pool["FTM"] - lg * pool["FTA"]
        else:
            impact = pool[cat]
        params[cat] = {"mean": float(impact.mean()), "std": float(impact.std() or 1.0), "lg": lg}
    return params


def apply_category_z(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Z-score columns (Z_<cat>) for any per-game frame: projections or single games."""
    z = pd.DataFrame(index=df.index)
    for cat, p in params.items():
        if cat == "FG_PCT":
            impact = df["FGM"] - p["lg"] * df["FGA"]
        elif cat == "FT_PCT":
            impact = df["FTM"] - p["lg"] * df["FTA"]
        else:
            impact = df[cat]
        zc = (impact - p["mean"]) / p["std"]
        z["Z_" + cat] = -zc if cat in LOWER_IS_BETTER else zc
    return z


def category_zscores(proj: pd.DataFrame, settings: LeagueSettings) -> tuple[pd.DataFrame, dict]:
    """Per-game z-scores against the draftable pool (two passes: everyone, then the top of the pool)."""
    zcols = ["Z_" + c for c in settings.active_categories]
    pool_size = min(settings.replacement_rank, len(proj))
    z = apply_category_z(proj, category_params(proj, settings))
    pool = proj.loc[z[zcols].sum(axis=1).nlargest(pool_size).index]
    params = category_params(pool, settings)
    return apply_category_z(proj, params), params


def per_game_value(df: pd.DataFrame, settings: LeagueSettings, params: dict | None) -> pd.Series:
    """Value of per-game lines (projections or single games) in this league's format."""
    if settings.scoring_type == "points":
        return sum(df[s] * v for s, v in settings.point_values.items())
    z = apply_category_z(df, params)
    return z[["Z_" + c for c in settings.active_categories]].sum(axis=1)


def get_player_values(
    logs: pd.DataFrame,
    settings: LeagueSettings,
    seasons: list[str] | None = None,
    positions: pd.DataFrame | None = None,
    overrides: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Ranked player values. `seasons` is ordered most recent first (default: ALL_SEASONS).

    `overrides` (optional CSV) has PLAYER_NAME plus any of GAMES, POSITIONS, TEAM
    to hand-correct projections (injuries, trades, Yahoo position eligibility).
    The returned frame's .attrs["params"] holds the category parameters, which
    trends.py reuses to value single games on the same scale."""
    proj = project_per_game(logs, seasons)

    if positions is not None and not positions.empty:
        proj = proj.merge(positions.drop_duplicates("PLAYER_ID"), on="PLAYER_ID", how="left")
        proj["POSITIONS"] = proj["NBA_POSITION"].apply(eligible_positions)
        proj = proj.drop(columns=["NBA_POSITION"])
    else:
        proj["POSITIONS"] = ""
    if overrides is not None and not overrides.empty:
        proj = apply_overrides(proj, overrides)

    params = None
    if settings.scoring_type == "points":
        proj["FPPG"] = per_game_value(proj, settings, None)
        proj["PER_GAME_VALUE"] = proj["FPPG"]
    else:
        z, params = category_zscores(proj, settings)
        proj = proj.join(z)
        proj["PER_GAME_VALUE"] = z[["Z_" + c for c in settings.active_categories]].sum(axis=1)

    by_pg = proj["PER_GAME_VALUE"].sort_values(ascending=False)
    repl = by_pg.iloc[min(settings.replacement_rank, len(by_pg)) - 1]
    aw = settings.availability_weight
    proj["REPLACEMENT"] = repl
    proj["VALUE"] = (proj["PER_GAME_VALUE"] - repl) * (1 - aw + aw * proj["GAMES"] / MAX_GAMES)
    proj = proj.sort_values("VALUE", ascending=False).reset_index(drop=True)
    proj["RANK"] = range(1, len(proj) + 1)
    proj["PER_GAME_RANK"] = proj["PER_GAME_VALUE"].rank(ascending=False, method="first").astype(int)
    proj.attrs["params"] = params
    return proj


def apply_overrides(proj: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    proj = proj.copy()
    for _, o in overrides.iterrows():
        mask = proj["PLAYER_NAME"].str.lower() == str(o["PLAYER_NAME"]).strip().lower()
        for col in ["GAMES", "POSITIONS", "TEAM"]:
            if col in o and pd.notna(o[col]) and str(o[col]).strip() != "":
                proj.loc[mask, col] = float(o[col]) if col == "GAMES" else str(o[col]).strip()
    return proj
