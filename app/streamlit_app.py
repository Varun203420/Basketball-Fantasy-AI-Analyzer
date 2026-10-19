"""Fantasy basketball assistant. Run from the repo root:  streamlit run app/streamlit_app.py"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import engine.data as data  # noqa: E402
from engine import (ALL_SEASONS, CURRENT_SEASON, NINE_CAT, YAHOO_DEFAULT_POINTS, DraftState,  # noqa: E402
                    LeagueSettings, cat_label, get_player_values, open_starter_slots, recent_form,
                    recommend_pick, rising_players, falling_players, team_category_totals, team_games,
                    week_bounds, weekly_games_table)
import agent  # noqa: E402

st.set_page_config(page_title="Fantasy Assistant", page_icon="🏀", layout="wide")
TODAY = date.today()

QUICK_PROMPTS = [
    "Who should I pick up this week?",
    "Any injury news I should know about for my team?",
    "Who's rising right now that I could grab?",
    "Which of my players are slumping, and should I worry?",
]


# ================================================================ data
def data_folder() -> tuple[Path, bool]:
    if any(data.game_log_path(s).exists() for s in ALL_SEASONS):
        return data.DATA_DIR, False
    return data.DATA_DIR / "sample", True


@st.cache_data(show_spinner="Loading game logs...")
def load_logs(folder: str, version: tuple) -> pd.DataFrame:
    data.DATA_DIR = Path(folder)
    return data.load_game_logs(ALL_SEASONS)


@st.cache_data(show_spinner="Crunching projections...")
def build_values(folder: str, version: tuple, settings_key: tuple) -> pd.DataFrame:
    num_teams, scoring_type, punt, points, aw = settings_key
    data.DATA_DIR = Path(folder)
    logs = load_logs(folder, version)
    overrides_path = ROOT / "data" / "overrides.csv"
    overrides = pd.read_csv(overrides_path) if overrides_path.exists() else None
    settings = LeagueSettings(num_teams=num_teams, scoring_type=scoring_type, punt=list(punt),
                              point_values=dict(points), availability_weight=aw)
    return get_player_values(logs, settings, positions=data.load_positions(), overrides=overrides)


# ================================================================ sidebar
st.sidebar.header("League")
num_teams = st.sidebar.number_input("Teams", 4, 20, 10)
scoring_type = st.sidebar.radio("Scoring", ["categories", "points"], format_func=str.title, horizontal=True)
punt, points = [], dict(YAHOO_DEFAULT_POINTS)
if scoring_type == "categories":
    punt = st.sidebar.multiselect("Punt categories", NINE_CAT, format_func=cat_label)
else:
    with st.sidebar.expander("Point values"):
        for stat in points:
            points[stat] = st.number_input(stat, value=float(points[stat]), step=0.1, key=f"pts_{stat}")
aw = st.sidebar.slider("Injury-risk weight", 0.0, 1.0, 0.5, 0.1,
                       help="0 ranks purely per game. 1 fully scales value by projected games played.")

settings = LeagueSettings(num_teams=int(num_teams), scoring_type=scoring_type, punt=punt,
                          point_values=points, availability_weight=aw)
folder, is_sample = data_folder()
data.DATA_DIR = folder
version = data.data_version(ALL_SEASONS, CURRENT_SEASON)
try:
    logs = load_logs(str(folder), version)
    values = build_values(str(folder), version, (settings.num_teams, scoring_type, tuple(punt),
                                                 tuple(points.items()), aw))
except FileNotFoundError:
    st.error("No data found. Run `python scripts/pull_data.py` (real data) or "
             "`python scripts/make_sample_data.py` (fake data for testing).")
    st.stop()
schedule = data.load_schedule(CURRENT_SEASON)
data_as_of = logs["GAME_DATE"].max().date()

st.sidebar.divider()
if is_sample:
    st.sidebar.warning("Using **sample data** (fake players). Run `python scripts/pull_data.py` for real stats.")
st.sidebar.caption(f"Box scores through **{data_as_of:%b %d, %Y}**. "
                   f"Schedule: {'loaded' if not schedule.empty else 'missing'}. "
                   f"Refresh with `python scripts/pull_data.py --daily`.")
if (TODAY - data_as_of).days > 3:
    st.sidebar.caption(f"No {CURRENT_SEASON} games in the data yet, so trends use the latest games available.")

# ================================================================ state
ss = st.session_state
ss.setdefault("picks", [])
ss.setdefault("roster", [])
ss.setdefault("taken_manual", [])
ss.setdefault("chat", [])
ss.setdefault("my_slot", 5)
ss.setdefault("form_window", 14)

if ss.my_slot > num_teams:
    ss.my_slot = int(num_teams)
names = values.set_index("PLAYER_ID")["PLAYER_NAME"].to_dict()
draft = DraftState(int(num_teams), int(ss.my_slot), list(ss.picks))
my_ids = [p for p in ss.roster if p in names]


def record_pick(pid) -> None:
    """Record a draft pick; our own picks also go onto our roster."""
    if draft.team_for_pick(len(ss.picks) + 1) == draft.my_slot and pid not in ss.roster:
        ss.roster.append(pid)
    ss.picks.append(pid)


def undo_pick() -> None:
    pid = ss.picks.pop()
    if draft.team_for_pick(len(ss.picks) + 1) == draft.my_slot and pid in ss.roster:
        ss.roster.remove(pid)
taken_ids = (set(ss.picks) - set(my_ids)) | set(ss.taken_manual)

form_window = ss.form_window
form = recent_form(logs, values, settings, window_days=form_window)
_, sunday = week_bounds(TODAY)
week_games = team_games(schedule, TODAY, sunday) if not schedule.empty else pd.Series(dtype=int)

ctx = agent.Context(values=values, settings=settings, form=form, schedule=schedule, today=TODAY,
                    data_as_of=data_as_of, my_ids=my_ids, taken_ids=taken_ids,
                    draft=draft if ss.picks else None)


def show_players(df: pd.DataFrame, extra: list | None = None) -> None:
    cols = ["RANK", "PLAYER_NAME", "TEAM", "POSITIONS", "GAMES", "VALUE"] + (extra or [])
    out = df[[c for c in cols if c in df]].copy()
    if not week_games.empty:
        out["Games left this week"] = df["TEAM"].map(week_games).fillna(0).astype(int)
    out = out.rename(columns={"PLAYER_NAME": "Player", "GAMES": "Proj. games", "VALUE": "Value"})
    st.dataframe(out.round(2), hide_index=True, width="stretch")


# ================================================================ chat engine
def trimmed(history: list, max_turns: int = 6) -> list:
    """Last few user turns (each with its tool calls), to bound cost."""
    starts = [i for i, m in enumerate(history) if m["role"] == "user" and isinstance(m["content"], str)]
    return list(history[starts[-max_turns]:] if len(starts) > max_turns else history)


def ask(prompt: str, status=None) -> None:
    import anthropic
    send = trimmed(ss.chat) + [{"role": "user", "content": prompt}]
    before = len(send)

    def on_event(name, args):
        if status is not None:
            status.write("🔎 " + (f"Searching the web: {args.get('query', '')}" if name == "web_search"
                                  else f"Checking {name.replace('_', ' ')}"))
    try:
        agent.run(anthropic.Anthropic(), agent_model(), send, ctx, on_event)
    except Exception as e:  # leave history untouched so the user can retry
        st.error(f"The assistant hit an error: {e}")
        return
    ss.chat.extend([{"role": "user", "content": prompt}] + send[before:])


def agent_model() -> str:
    import os
    return os.getenv("ANTHROPIC_MODEL", agent.DEFAULT_MODEL)


def render_chat() -> None:
    turn = None
    for m in ss.chat:
        if m["role"] == "user" and isinstance(m["content"], str):
            if turn:
                draw_turn(*turn)
            turn = (m["content"], [], [], [])
        elif m["role"] == "assistant" and turn:
            text, sources, activity = agent.render_parts(m["content"])
            turn[1].append(text)
            turn[2].extend(s for s in sources if s not in turn[2])
            turn[3].extend(activity)
    if turn:
        draw_turn(*turn)


def draw_turn(prompt, texts, sources, activity) -> None:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        if activity:
            with st.expander(f"Looked at {len(activity)} thing{'s' if len(activity) != 1 else ''}"):
                st.markdown("\n".join(f"- {a}" for a in activity))
        answer = [t for t in texts if t.strip()]
        st.markdown(answer[-1] if answer else "_No answer._")   # final answer, not the "let me check" preamble
        if sources:
            st.caption("Sources: " + " · ".join(f"[{t}]({u})" for t, u in sources[:6]))


# ================================================================ tabs
tab_chat, tab_team, tab_trend, tab_sched, tab_draft, tab_rank = st.tabs(
    ["💬 Assistant", "👥 My team", "📈 Trending", "📅 Schedule", "🏀 Draft", "📋 Rankings"])

# ---------------- Assistant
with tab_chat:
    if not agent.available():
        st.info("Add `ANTHROPIC_API_KEY=...` to a `.env` file in the repo folder, then restart the app.")
    else:
        if not my_ids:
            st.caption("Tip: add your players in **My team** so the assistant can give roster-specific advice.")
        cols = st.columns(len(QUICK_PROMPTS))
        for col, q in zip(cols, QUICK_PROMPTS):
            if col.button(q, width="stretch"):
                ss.pending = q
        if ss.chat and st.button("Clear chat"):
            ss.chat = []
            st.rerun()
        render_chat()
        prompt = st.chat_input("Ask about pickups, trades, injuries, matchups...")
        prompt = prompt or ss.pop("pending", None)
        if prompt:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.status("Thinking...", expanded=True) as status:
                    ask(prompt, status)
                    status.update(label="Done", state="complete", expanded=False)
            st.rerun()

# ---------------- My team
with tab_team:
    st.subheader("Our roster")
    all_ids = values.sort_values("PLAYER_NAME")["PLAYER_ID"].tolist()
    roster = st.multiselect("Players on our team", all_ids, default=[p for p in my_ids if p in names],
                            format_func=lambda p: names[p])
    if set(roster) != set(my_ids):
        ss.roster = roster
        st.rerun()
    taken = st.multiselect("Players on other teams (optional, keeps them out of pickup suggestions)", all_ids,
                           default=[p for p in ss.taken_manual if p in names], format_func=lambda p: names[p])
    if set(taken) != set(ss.taken_manual):
        ss.taken_manual = taken
        st.rerun()
    st.caption("Players you draft in the Draft tab are added automatically. Yahoo sync is planned.")
    mine = values[values["PLAYER_ID"].isin(roster)]
    if mine.empty:
        st.info("Add your players above.")
    else:
        show_players(mine)
        c1, c2 = st.columns(2)
        slots = open_starter_slots([{x for x in str(p).split(",") if x} for p in mine["POSITIONS"]], settings)
        c1.metric("Open starting slots", ", ".join(slots) if slots else "None")
        if not week_games.empty:
            c2.metric("Games left this week", int(sum(week_games.get(t, 0) for t in mine["TEAM"])))
        if scoring_type == "categories":
            totals = team_category_totals(values, roster, settings)
            st.caption("Category strength (sum of z-scores; higher is better)")
            st.bar_chart(pd.DataFrame({"Category": [cat_label(c[2:]) for c in totals.index],
                                       "Strength": totals.values}), x="Category", y="Strength")

# ---------------- Trending
with tab_trend:
    c1, c2 = st.columns([1, 2])
    c1.select_slider("Window", [7, 14, 30], key="form_window", format_func=lambda d: f"{d} days")
    avail_only = c2.toggle("Only players not on a roster", value=True)
    if form.empty:
        st.info("No recent games in the data.")
    else:
        st.caption(f"Performance over the {form_window} days ending {form.attrs['as_of']:%b %d, %Y}, "
                   "compared with each player's projection. Value is per game, on the same scale as rankings.")
        cols = ["PLAYER_NAME", "TEAM", "RANK", "GP_RECENT", "MPG_PROJECTED", "MPG_RECENT", "VALUE_PROJECTED",
                "VALUE_RECENT", "VALUE_DELTA"]
        labels = {"PLAYER_NAME": "Player", "GP_RECENT": "Games", "MPG_PROJECTED": "Proj. min",
                  "MPG_RECENT": "Recent min", "VALUE_PROJECTED": "Proj. value", "VALUE_RECENT": "Recent value",
                  "VALUE_DELTA": "Change"}
        st.subheader("Rising")
        rise = rising_players(form, 20, exclude_ids=(taken_ids | set(my_ids)) if avail_only else None)
        rise.attrs = {}
        st.dataframe(rise[cols].rename(columns=labels).round(1), hide_index=True, width="stretch")
        if my_ids:
            st.subheader("Our players, coldest first")
            fall = falling_players(form, 13, ids=set(my_ids))
            fall.attrs = {}
            st.dataframe(fall[cols].rename(columns=labels).round(1), hide_index=True, width="stretch")

# ---------------- Schedule
with tab_sched:
    if schedule.empty:
        st.info(f"No {CURRENT_SEASON} schedule yet. Run `python scripts/pull_data.py --daily`.")
    else:
        table = weekly_games_table(schedule, TODAY, weeks=3)
        st.caption("Games per team. More games means more counting stats in a head-to-head week.")
        if my_ids:
            mine = values[values["PLAYER_ID"].isin(my_ids)]
            ours = {col: int(sum(table[col].get(t, 0) for t in mine["TEAM"])) for col in table.columns}
            st.markdown("**Our team's total games:** " + " · ".join(f"{k}: {v}" for k, v in ours.items()))
        st.dataframe(table, width="stretch")

# ---------------- Draft
with tab_draft:
    c1, c2 = st.columns(2)
    c1.number_input("Our draft position", 1, int(num_teams), key="my_slot")
    if c2.button("Reset draft"):
        while ss.picks:
            undo_pick()
        st.rerun()
    rounds = settings.rostered_per_team
    total_picks = rounds * draft.num_teams
    done = draft.current_pick > total_picks
    wait = draft.picks_until_my_turn(rounds)
    if done:
        st.success("Draft complete. Your picks are on the My team tab.")
    else:
        on_clock = draft.team_for_pick(draft.current_pick)
        m1, m2, m3 = st.columns(3)
        m1.metric("Pick", f"{draft.current_pick} of {total_picks}",
                  f"Round {(draft.current_pick - 1) // draft.num_teams + 1}", delta_color="off")
        m2.metric("On the clock", "You" if on_clock == draft.my_slot else f"Team {on_clock}")
        m3.metric("Picks until your turn", "Now" if wait == 0 else ("—" if wait is None else wait))

        left, right = st.columns([3, 2], gap="large")
        with left:
            st.subheader("Recommended")
            recs = recommend_pick(values, draft, settings, top_n=10)
            for _, r in recs.iterrows():
                row = st.columns([4, 1])
                gone = " · ⚠️ likely gone before your next pick" if r["LIKELY_GONE"] and wait != 0 else ""
                row[0].markdown(f"**{r['PLAYER_NAME']}** ({r['TEAM']}, {r['POSITIONS'] or '?'}) — "
                                f"score {r['SCORE']:.2f}{gone}  \n<small>{r['REASONS']}</small>",
                                unsafe_allow_html=True)
                if row[1].button("Draft", key=f"rec_{r['PLAYER_ID']}"):
                    record_pick(r["PLAYER_ID"])
                    st.rerun()
            if agent.available() and st.button("Ask the assistant about this pick"):
                with st.status("Thinking...", expanded=True) as status:
                    ask("We're on the clock or close to it. Which of the recommended picks should we take, and "
                        "why? Check news on the top options for injuries.", status)
                    status.update(label="Done (full answer is in the Assistant tab)", state="complete")
                texts = [agent.render_parts(m["content"])[0] for m in ss.chat[-3:] if m["role"] == "assistant"]
                st.info(texts[-1] if texts else "No answer.")
            st.subheader("Record any pick")
            avail = values[~values["PLAYER_ID"].isin(draft.picks)]
            choice = st.selectbox("Player", avail["PLAYER_ID"], format_func=lambda p: names[p], index=None,
                                  placeholder="Type a name...")
            if st.button("Mark drafted", disabled=choice is None):
                record_pick(choice)
                st.rerun()
            if ss.picks and st.button("Undo last pick"):
                undo_pick()
                st.rerun()
        with right:
            st.subheader("Our picks")
            mine = values[values["PLAYER_ID"].isin(draft.my_players())]
            if mine.empty:
                st.caption("No players yet.")
            else:
                st.dataframe(mine[["PLAYER_NAME", "TEAM", "POSITIONS"]].rename(columns=str.title),
                             hide_index=True, width="stretch")
                slots = open_starter_slots([{x for x in str(p).split(",") if x} for p in mine["POSITIONS"]], settings)
                st.caption("Open starting slots: " + (", ".join(slots) if slots else "none"))
            with st.expander("Draft log"):
                st.dataframe(pd.DataFrame([{"Pick": i, "Team": draft.team_for_pick(i), "Player": names.get(p, p)}
                                           for i, p in enumerate(ss.picks, start=1)]),
                             hide_index=True, width="stretch")

# ---------------- Rankings
with tab_rank:
    q = st.text_input("Search", placeholder="Player or team")
    v = values
    if q:
        v = v[v["PLAYER_NAME"].str.contains(q, case=False) | v["TEAM"].str.contains(q, case=False)]
    extra = ["PER_GAME_RANK"] + (["Z_" + c for c in NINE_CAT] if scoring_type == "categories" else ["FPPG"])
    show = v[["RANK", "PLAYER_NAME", "TEAM", "POSITIONS", "GAMES", "VALUE"] + extra].copy()
    show.insert(1, "Status", v["PLAYER_ID"].map(lambda p: "Ours" if p in my_ids else ("Taken" if p in taken_ids else "")))
    st.dataframe(show.rename(columns=lambda c: cat_label(c[2:]) if c.startswith("Z_") else c).round(2),
                 hide_index=True, width="stretch")
