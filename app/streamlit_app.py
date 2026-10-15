"""Draft board. Run from the repo root:  streamlit run app/streamlit_app.py"""
import sys
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
from engine import (DraftState, LeagueSettings, NINE_CAT, YAHOO_DEFAULT_POINTS, cat_label,  # noqa: E402
                    get_player_values, open_starter_slots, recommend_pick, team_category_totals)
import llm  # noqa: E402

SEASONS = ["2025-26", "2024-25"]   # most recent first

st.set_page_config(page_title="Draft Assistant", page_icon="🏀", layout="wide")


# ---------- data ----------
def data_dir() -> tuple[Path, bool]:
    real = data.DATA_DIR
    if data.game_log_path(SEASONS[0]).exists():
        return real, False
    return real / "sample", True


@st.cache_data(show_spinner="Crunching projections...")
def build_values(folder: str, settings_key: tuple) -> pd.DataFrame:
    num_teams, scoring_type, punt, points = settings_key
    data.DATA_DIR = Path(folder)
    logs = data.load_game_logs(SEASONS)
    positions = data.load_positions()
    overrides_path = ROOT / "data" / "overrides.csv"
    overrides = pd.read_csv(overrides_path) if overrides_path.exists() else None
    settings = LeagueSettings(num_teams=num_teams, scoring_type=scoring_type, punt=list(punt), point_values=dict(points))
    return get_player_values(logs, settings, SEASONS, positions=positions, overrides=overrides)


# ---------- sidebar: league ----------
st.sidebar.header("League")
num_teams = st.sidebar.number_input("Teams", 4, 20, 10)
my_slot = st.sidebar.number_input("Our draft position", 1, int(num_teams), 5)
scoring_type = st.sidebar.radio("Scoring", ["categories", "points"], format_func=str.title)
punt, points = [], dict(YAHOO_DEFAULT_POINTS)
if scoring_type == "categories":
    punt = st.sidebar.multiselect("Punt categories", NINE_CAT, format_func=cat_label)
else:
    st.sidebar.caption("Point values")
    for stat in points:
        points[stat] = st.sidebar.number_input(stat, value=float(points[stat]), step=0.1, key=f"pts_{stat}")

settings = LeagueSettings(num_teams=int(num_teams), scoring_type=scoring_type, punt=punt, point_values=points)
folder, is_sample = data_dir()
try:
    values = build_values(str(folder), (settings.num_teams, scoring_type, tuple(punt), tuple(points.items())))
except FileNotFoundError:
    st.error("No data found. Run `python scripts/pull_data.py` (real data) or "
             "`python scripts/make_sample_data.py` (fake data for testing).")
    st.stop()

if is_sample:
    st.sidebar.warning("Using **sample data** (fake players). Run `python scripts/pull_data.py` for real stats.")

if st.sidebar.button("Reset draft", type="secondary"):
    st.session_state.picks = []

# ---------- draft state ----------
if "picks" not in st.session_state:
    st.session_state.picks = []
draft = DraftState(int(num_teams), int(my_slot), list(st.session_state.picks))
rounds = settings.rostered_per_team
total_picks = rounds * draft.num_teams
names = values.set_index("PLAYER_ID")["PLAYER_NAME"].to_dict()


def record_pick(player_id) -> None:
    st.session_state.picks.append(player_id)


# ---------- header ----------
done = draft.current_pick > total_picks
if done:
    st.title("Draft complete")
else:
    on_clock = draft.team_for_pick(draft.current_pick)
    rnd = (draft.current_pick - 1) // draft.num_teams + 1
    wait = draft.picks_until_my_turn(rounds)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pick", f"{draft.current_pick} of {total_picks}", f"Round {rnd}", delta_color="off")
    c2.metric("On the clock", "You" if on_clock == draft.my_slot else f"Team {on_clock}")
    c3.metric("Picks until your turn", "Now" if wait == 0 else ("—" if wait is None else wait))
    if on_clock == draft.my_slot:
        st.success("You're on the clock.")

left, right = st.columns([3, 2], gap="large")

# ---------- left: recommendations and pick entry ----------
with left:
    if not done:
        st.subheader("Recommended")
        recs = recommend_pick(values, draft, settings, top_n=10)
        for _, r in recs.iterrows():
            row = st.columns([4, 1])
            gone = " · ⚠️ likely gone before your next pick" if r["LIKELY_GONE"] and wait != 0 else ""
            row[0].markdown(f"**{r['PLAYER_NAME']}** ({r['TEAM']}, {r['POSITIONS'] or '?'}) — "
                            f"score {r['SCORE']:.2f}{gone}  \n<small>{r['REASONS']}</small>",
                            unsafe_allow_html=True)
            row[1].button("Draft", key=f"rec_{r['PLAYER_ID']}", on_click=record_pick, args=(r["PLAYER_ID"],),
                          help="Record this player as taken by the team on the clock")

        if llm.available():
            if st.button("Ask Claude to explain"):
                mine = [names[p] for p in draft.my_players()]
                lines = "\n".join(f"{i + 1}. {r['PLAYER_NAME']} ({r['POSITIONS']}): score {r['SCORE']:.2f}; "
                                  f"{r['REASONS']}; likely gone before next pick: {r['LIKELY_GONE']}"
                                  for i, r in recs.head(5).iterrows())
                context = (f"League: {settings.num_teams} teams, {scoring_type}"
                           f"{', punting ' + ', '.join(cat_label(c) for c in punt) if punt else ''}.\n"
                           f"Pick {draft.current_pick}, picks until our turn: {wait}.\n"
                           f"Our roster: {', '.join(mine) or 'empty'}.\nEngine's top options:\n{lines}")
                with st.spinner("Asking Claude..."):
                    try:
                        st.info(llm.explain_pick(context))
                    except Exception as e:  # network, key, or model errors shouldn't break the draft
                        st.error(f"Claude call failed: {e}")
        else:
            st.caption("Add ANTHROPIC_API_KEY to .env to get Claude explanations.")

        st.subheader("Record any pick")
        avail = values[~values["PLAYER_ID"].isin(draft.picks)]
        choice = st.selectbox("Player", avail["PLAYER_ID"], format_func=lambda pid: names[pid],
                              index=None, placeholder="Type a name...")
        st.button("Mark drafted", disabled=choice is None, on_click=record_pick, args=(choice,))

    if st.session_state.picks and st.button("Undo last pick"):
        st.session_state.picks.pop()
        st.rerun()

# ---------- right: our team ----------
with right:
    st.subheader("Our team")
    my_ids = draft.my_players()
    mine = values[values["PLAYER_ID"].isin(my_ids)]
    if mine.empty:
        st.caption("No players yet.")
    else:
        st.dataframe(mine[["PLAYER_NAME", "TEAM", "POSITIONS", "GAMES"]].rename(columns=str.title),
                     hide_index=True, width="stretch")
        slots = open_starter_slots([{p for p in str(x).split(",") if p} for x in mine["POSITIONS"]], settings)
        st.caption("Open starting slots: " + (", ".join(slots) if slots else "none"))
        if scoring_type == "categories":
            totals = team_category_totals(values, my_ids, settings)
            chart = pd.DataFrame({"Category": [cat_label(c[2:]) for c in totals.index], "Strength": totals.values})
            st.caption("Category strength (sum of z-scores; higher is better)")
            st.bar_chart(chart, x="Category", y="Strength")

    with st.expander("Draft log"):
        log = [{"Pick": i, "Team": draft.team_for_pick(i), "Player": names.get(p, p)}
               for i, p in enumerate(st.session_state.picks, start=1)]
        st.dataframe(pd.DataFrame(log), hide_index=True, width="stretch")

# ---------- full rankings ----------
with st.expander("All rankings"):
    cols = ["RANK", "PLAYER_NAME", "TEAM", "POSITIONS", "GAMES", "VALUE"]
    if scoring_type == "categories":
        cols += ["Z_" + c for c in NINE_CAT]
    else:
        cols += ["FPPG"]
    show = values[cols].copy()
    show["TAKEN"] = show["PLAYER_ID"].isin(draft.picks) if "PLAYER_ID" in show else values["PLAYER_ID"].isin(draft.picks)
    st.dataframe(show.rename(columns=lambda c: cat_label(c[2:]) if c.startswith("Z_") else c.title()).round(2),
                 hide_index=True, width="stretch")
