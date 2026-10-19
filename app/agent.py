"""Chat assistant: Claude with tools over the engine, plus web search for news.

The engine computes every number. Claude decides which tools to call, combines
the results with injury and lineup news from web search, and explains. The
system prompt forbids inventing stats.

Needs ANTHROPIC_API_KEY in .env. Model: ANTHROPIC_MODEL (default below).
"""
import difflib
import json
import os
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from engine import (DraftState, LeagueSettings, cat_label, open_starter_slots, recommend_pick,
                    team_category_totals, team_games, week_bounds)
from engine.trends import falling_players, rising_players

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_STEPS = 10
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


@dataclass
class Context:
    """Everything the tools can see. Built fresh by the app on each rerun."""
    values: pd.DataFrame
    settings: LeagueSettings
    form: pd.DataFrame
    schedule: pd.DataFrame
    today: date
    data_as_of: date | None
    my_ids: list = field(default_factory=list)
    taken_ids: set = field(default_factory=set)
    draft: DraftState | None = None


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------- helpers

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def _find(ctx: Context, name: str):
    names = ctx.values["PLAYER_NAME"].map(_norm)
    q = _norm(name)
    hits = ctx.values[names == q]
    if hits.empty:
        hits = ctx.values[names.str.contains(q, regex=False)]
    if hits.empty:
        close = difflib.get_close_matches(q, names.tolist(), n=1, cutoff=0.6)
        hits = ctx.values[names == close[0]] if close else hits
    return hits.iloc[0] if len(hits) else None


def _week_games(ctx: Context) -> pd.Series:
    if ctx.schedule.empty:
        return pd.Series(dtype=int)
    _, sunday = week_bounds(ctx.today)
    return team_games(ctx.schedule, ctx.today, sunday)


def _status(ctx: Context, pid) -> str:
    if pid in ctx.my_ids:
        return "on our team"
    return "rostered elsewhere" if pid in ctx.taken_ids else "available"


def _r(x, nd=2):
    return None if pd.isna(x) else round(float(x), nd)


def _summary(ctx: Context, p, games_week: pd.Series) -> dict:
    out = {
        "name": p["PLAYER_NAME"], "team": p["TEAM"], "positions": p["POSITIONS"] or "unknown",
        "rank": int(p["RANK"]), "per_game_rank": int(p["PER_GAME_RANK"]),
        "value": _r(p["VALUE"]), "status": _status(ctx, p["PLAYER_ID"]),
        "projected_games": _r(p["GAMES"], 0),
    }
    if not games_week.empty:
        out["games_rest_of_week"] = int(games_week.get(p["TEAM"], 0))
    return out


def _profile(ctx: Context, p, games_week: pd.Series) -> dict:
    out = _summary(ctx, p, games_week)
    out["projection_per_game"] = {k: _r(p[k], 1) for k in ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M", "TOV"]}
    out["projection_per_game"].update({"FG%": _r(p["FG_PCT"], 3), "FT%": _r(p["FT_PCT"], 3)})
    out["games_played_by_season"] = {c[3:]: int(p[c]) for c in p.index if c.startswith("GP_2")}
    if ctx.settings.scoring_type == "categories":
        out["category_zscores"] = {cat_label(c): _r(p["Z_" + c]) for c in ctx.settings.categories}
    else:
        out["fantasy_points_per_game"] = _r(p["FPPG"], 1)
    if not ctx.form.empty:
        f = ctx.form[ctx.form["PLAYER_ID"] == p["PLAYER_ID"]]
        if len(f):
            f = f.iloc[0]
            out["recent_form"] = {
                "window_days": ctx.form.attrs.get("window_days"), "games": int(f["GP_RECENT"]),
                "minutes": _r(f["MPG_RECENT"], 1), "projected_minutes": _r(f["MPG_PROJECTED"], 1),
                "value_per_game": _r(f["VALUE_RECENT"]), "projected_value_per_game": _r(f["VALUE_PROJECTED"]),
                "pts_reb_ast": [_r(f["PTS_RECENT"], 1), _r(f["REB_RECENT"], 1), _r(f["AST_RECENT"], 1)],
            }
    return out


# ---------------------------------------------------------------- tools

def tool_get_player(ctx: Context, name: str) -> dict:
    p = _find(ctx, name)
    if p is None:
        return {"error": f"No player matching '{name}'. Rookies with no NBA games aren't in the data."}
    return _profile(ctx, p, _week_games(ctx))


def tool_compare_players(ctx: Context, names: list) -> dict:
    gw = _week_games(ctx)
    found, missing = [], []
    for n in names[:5]:
        p = _find(ctx, n)
        (found.append(_profile(ctx, p, gw)) if p is not None else missing.append(n))
    return {"players": found, "not_found": missing}


def tool_get_rankings(ctx: Context, top_n: int = 15, position: str | None = None,
                      available_only: bool = False, sort_by: str = "value") -> dict:
    v = ctx.values
    if position:
        v = v[v["POSITIONS"].str.split(",").apply(lambda ps: position.upper() in ps)]
    if available_only:
        v = v[~v["PLAYER_ID"].isin(ctx.taken_ids) & ~v["PLAYER_ID"].isin(ctx.my_ids)]
    if sort_by == "per_game":
        v = v.sort_values("PER_GAME_VALUE", ascending=False)
    gw = _week_games(ctx)
    return {"players": [_summary(ctx, p, gw) for _, p in v.head(min(top_n, 40)).iterrows()]}


def tool_get_my_team(ctx: Context) -> dict:
    if not ctx.my_ids:
        return {"error": "Our roster is empty. Ask the user to add players in the 'My team' tab or draft some."}
    gw = _week_games(ctx)
    mine = ctx.values[ctx.values["PLAYER_ID"].isin(ctx.my_ids)]
    out = {"players": [_summary(ctx, p, gw) for _, p in mine.iterrows()]}
    if not gw.empty:
        out["total_games_rest_of_week"] = int(sum(gw.get(t, 0) for t in mine["TEAM"]))
    if ctx.settings.scoring_type == "categories":
        totals = team_category_totals(ctx.values, ctx.my_ids, ctx.settings)
        out["category_strength"] = {cat_label(c[2:]): _r(x) for c, x in totals.items()}
        out["weakest_categories"] = [cat_label(c[2:]) for c in totals.nsmallest(3).index]
    out["open_starting_slots"] = open_starter_slots(
        [{x for x in str(p).split(",") if x} for p in mine["POSITIONS"]], ctx.settings)
    return out


def tool_get_rising_players(ctx: Context, top_n: int = 10, available_only: bool = True) -> dict:
    if ctx.form.empty:
        return {"error": "No recent games in the data."}
    exclude = (set(ctx.taken_ids) | set(ctx.my_ids)) if available_only else None
    r = rising_players(ctx.form, top_n=min(top_n, 25), exclude_ids=exclude)
    return {"as_of": str(ctx.form.attrs.get("as_of")), "window_days": ctx.form.attrs.get("window_days"),
            "players": [_profile(ctx, ctx.values[ctx.values["PLAYER_ID"] == pid].iloc[0], _week_games(ctx))
                        for pid in r["PLAYER_ID"]]}


def tool_get_my_slumping_players(ctx: Context) -> dict:
    if ctx.form.empty or not ctx.my_ids:
        return {"error": "Need recent games and a roster."}
    f = falling_players(ctx.form, top_n=5, ids=set(ctx.my_ids))
    return {"as_of": str(ctx.form.attrs.get("as_of")),
            "players": [{"name": r["PLAYER_NAME"], "minutes": _r(r["MPG_RECENT"], 1),
                         "projected_minutes": _r(r["MPG_PROJECTED"], 1), "value_recent": _r(r["VALUE_RECENT"]),
                         "value_projected": _r(r["VALUE_PROJECTED"])} for _, r in f.iterrows()]}


def tool_get_schedule(ctx: Context, team: str | None = None, weeks_ahead: int = 0) -> dict:
    if ctx.schedule.empty:
        return {"error": "No schedule data. Run: python scripts/pull_data.py --daily"}
    monday, sunday = week_bounds(ctx.today + timedelta(weeks=weeks_ahead))
    start = max(monday, ctx.today)
    counts = team_games(ctx.schedule, start, sunday)
    out = {"from": str(start), "to": str(sunday)}
    if team:
        t = team.upper()
        s = ctx.schedule[(ctx.schedule["GAME_DATE"] >= start) & (ctx.schedule["GAME_DATE"] <= sunday)]
        g = s[(s["HOME"] == t) | (s["AWAY"] == t)]
        out["team"] = t
        out["games"] = [{"date": str(r["GAME_DATE"]), "opponent": r["AWAY"] if r["HOME"] == t else r["HOME"],
                         "home": r["HOME"] == t} for _, r in g.iterrows()]
    else:
        out["games_per_team"] = {k: int(v) for k, v in counts.items()}
    return out


def tool_recommend_draft_pick(ctx: Context, top_n: int = 8) -> dict:
    if ctx.draft is None:
        return {"error": "No draft in progress."}
    recs = recommend_pick(ctx.values, ctx.draft, ctx.settings, top_n=min(top_n, 15))
    rounds = ctx.settings.rostered_per_team
    return {"pick": ctx.draft.current_pick, "picks_until_our_turn": ctx.draft.picks_until_my_turn(rounds),
            "options": [{"name": r["PLAYER_NAME"], "positions": r["POSITIONS"], "score": _r(r["SCORE"]),
                         "reasons": r["REASONS"], "likely_gone_before_next_pick": bool(r["LIKELY_GONE"])}
                        for _, r in recs.iterrows()]}


TOOLS = {
    "get_player": (tool_get_player, "Full profile of one player: rank, projection, category z-scores, games "
                   "played by season, recent form, games left this week, and whether he's available.",
                   {"name": {"type": "string", "description": "Player name (partial is fine)"}}, ["name"]),
    "compare_players": (tool_compare_players, "Side-by-side profiles of 2-5 players.",
                        {"names": {"type": "array", "items": {"type": "string"}}}, ["names"]),
    "get_rankings": (tool_get_rankings, "Top players by our engine's value. Use available_only=true for free "
                     "agents / undrafted players. sort_by 'per_game' ignores projected missed games.",
                     {"top_n": {"type": "integer"}, "position": {"type": "string", "description": "PG, SG, SF, PF or C"},
                      "available_only": {"type": "boolean"},
                      "sort_by": {"type": "string", "enum": ["value", "per_game"]}}, []),
    "get_my_team": (tool_get_my_team, "Our roster with values, category strengths, weakest categories, open "
                    "starting slots, and games remaining this week.", {}, []),
    "get_rising_players": (tool_get_rising_players, "Players performing above their projection recently "
                           "(value and minutes vs projection). Good pickup candidates.",
                           {"top_n": {"type": "integer"}, "available_only": {"type": "boolean"}}, []),
    "get_my_slumping_players": (tool_get_my_slumping_players, "Players on our roster performing below "
                                "projection recently.", {}, []),
    "get_schedule": (tool_get_schedule, "Games per team for the rest of this fantasy week (Mon-Sun), or one "
                     "team's game dates. weeks_ahead=1 for next week.",
                     {"team": {"type": "string", "description": "Team abbreviation, e.g. LAL"},
                      "weeks_ahead": {"type": "integer"}}, []),
    "recommend_draft_pick": (tool_recommend_draft_pick, "During a draft: the engine's ranked pick options for "
                             "us right now, with reasons.", {"top_n": {"type": "integer"}}, []),
}


def tool_specs() -> list:
    specs = [{"name": n, "description": d, "input_schema": {"type": "object", "properties": props, "required": req}}
             for n, (_, d, props, req) in TOOLS.items()]
    return specs + [WEB_SEARCH]


def call_tool(ctx: Context, name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"error": f"Unknown tool {name}"}
    try:
        return TOOLS[name][0](ctx, **(args or {}))
    except Exception as e:  # report tool errors to Claude instead of crashing the chat
        return {"error": f"{type(e).__name__}: {e}"}


def system_prompt(ctx: Context) -> str:
    s = ctx.settings
    fmt = (f"head-to-head categories ({', '.join(cat_label(c) for c in s.categories)})"
           + (f", punting {', '.join(cat_label(c) for c in s.punt)}" if s.punt else "")
           if s.scoring_type == "categories" else f"points ({s.point_values})")
    return f"""You are a fantasy basketball assistant for a {s.num_teams}-team Yahoo league scored as {fmt}.
Today is {ctx.today:%A, %B %d, %Y}. Box-score data runs through {ctx.data_as_of}.

How to work:
- Every stat, rank, projection, or schedule number must come from a tool result. Never invent or recall numbers.
- For injuries, return timelines, trades, lineup or role changes, use web_search and cite sources.
  Check news before recommending a pickup or drop, since the stats can't see injuries.
- Our engine's value combines per-game production with projected availability. Weakest categories are
  the ones to target with pickups. More games this week means more counting stats.
- If the box-score data is older than a few days, say so; recent-form tools reflect that date.
- Be direct and concise: lead with the recommendation, then the 2-3 reasons that matter, and say how
  confident you are. Use short lists or small tables when comparing players.
- "Available" means not on our roster and not drafted in this app. The app doesn't sync with Yahoo yet,
  so ask the user to confirm a player is really a free agent before they act."""


def run(client, model: str, messages: list, ctx: Context, on_event=None) -> list:
    """Run the tool loop until Claude answers. Appends to and returns `messages`."""
    for _ in range(MAX_STEPS):
        resp = client.messages.create(model=model, max_tokens=2000, system=system_prompt(ctx),
                                      tools=tool_specs(), messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":       # long web search: resend to continue
            continue
        if resp.stop_reason != "tool_use":
            break
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                if on_event:
                    on_event(block.name, block.input)
                out = call_tool(ctx, block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out, default=str)})
        messages.append({"role": "user", "content": results})
    return messages


def render_parts(content) -> tuple[str, list, list]:
    """Assistant message content -> (text, [(title, url)] sources, [activity lines])."""
    text, sources, activity = [], [], []
    for b in content if isinstance(content, list) else []:
        t = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
        if t == "text":
            text.append(b.text)
            for c in getattr(b, "citations", None) or []:
                url = getattr(c, "url", None)
                if url and url not in [u for _, u in sources]:
                    sources.append((getattr(c, "title", url) or url, url))
        elif t == "server_tool_use":
            activity.append(f"Searched the web: {b.input.get('query', '')}")
        elif t == "tool_use":
            args = ", ".join(f"{k}={v}" for k, v in (b.input or {}).items())
            activity.append(f"Checked {b.name.replace('_', ' ')}" + (f" ({args})" if args else ""))
    return "".join(text), sources, activity
