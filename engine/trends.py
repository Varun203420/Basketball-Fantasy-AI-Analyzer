"""Recent form: who is playing above or below their projection.

Each recent game is valued on the same scale as the projections (same category
z-score parameters, or the same fantasy points), then averaged per player over a
window of days. Comparing that to the player's projected per-game value and
projected minutes gives a "rising" or "falling" signal that works from the first
week of the season, since the baseline is the projection, not season-to-date.
"""
import pandas as pd

from .settings import LeagueSettings
from .valuation import per_game_value

MIN_RECENT_GAMES = 3


def recent_form(
    logs: pd.DataFrame,
    values: pd.DataFrame,
    settings: LeagueSettings,
    window_days: int = 14,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Per player: recent games, minutes and value vs projection, over the last `window_days`."""
    as_of = pd.Timestamp(as_of) if as_of is not None else logs["GAME_DATE"].max()
    recent = logs[(logs["GAME_DATE"] > as_of - pd.Timedelta(days=window_days)) & (logs["GAME_DATE"] <= as_of)].copy()
    if recent.empty:
        return pd.DataFrame()
    recent["GAME_VALUE"] = per_game_value(recent, settings, values.attrs.get("params"))
    agg = recent.groupby("PLAYER_ID").agg(
        GP_RECENT=("GAME_ID", "nunique"),
        MPG_RECENT=("MIN", "mean"),
        VALUE_RECENT=("GAME_VALUE", "mean"),
        PTS_RECENT=("PTS", "mean"),
        REB_RECENT=("REB", "mean"),
        AST_RECENT=("AST", "mean"),
        LAST_GAME=("GAME_DATE", "max"),
    )
    base = values.set_index("PLAYER_ID")[["PLAYER_NAME", "TEAM", "POSITIONS", "RANK", "MIN", "PER_GAME_VALUE"]]
    out = base.join(agg, how="inner").reset_index()
    out = out[out["GP_RECENT"] >= MIN_RECENT_GAMES]
    out["MIN_DELTA"] = out["MPG_RECENT"] - out["MIN"]
    out["VALUE_DELTA"] = out["VALUE_RECENT"] - out["PER_GAME_VALUE"]
    out.attrs["as_of"] = as_of.date()
    out.attrs["window_days"] = window_days
    return out.rename(columns={"MIN": "MPG_PROJECTED", "PER_GAME_VALUE": "VALUE_PROJECTED"})


def rising_players(form: pd.DataFrame, top_n: int = 15, min_minutes: float = 15.0,
                   exclude_ids: set | None = None) -> pd.DataFrame:
    """Biggest gains in value vs projection among players getting real minutes."""
    if form.empty:
        return form
    f = form[form["MPG_RECENT"] >= min_minutes]
    if exclude_ids:
        f = f[~f["PLAYER_ID"].isin(exclude_ids)]
    return f.sort_values("VALUE_DELTA", ascending=False).head(top_n)


def falling_players(form: pd.DataFrame, top_n: int = 15, ids: set | None = None) -> pd.DataFrame:
    """Biggest drops vs projection (optionally only within `ids`, e.g. our roster)."""
    if form.empty:
        return form
    f = form if ids is None else form[form["PLAYER_ID"].isin(ids)]
    return f.sort_values("VALUE_DELTA").head(top_n)
