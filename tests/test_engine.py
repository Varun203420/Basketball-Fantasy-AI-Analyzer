"""Engine tests on fake data. Run from the repo root:  pytest"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import DraftState, LeagueSettings, get_player_values, open_starter_slots, recommend_pick  # noqa: E402
from engine.data import _minutes  # noqa: E402
from engine.valuation import eligible_positions  # noqa: E402
from make_sample_data import make  # noqa: E402

SEASONS = ["2025-26", "2024-25"]


@pytest.fixture(scope="module")
def sample():
    logs, positions = make(n_players=180, seed=1)
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"])
    return logs, positions


def test_settings_defaults():
    s = LeagueSettings()
    assert s.rostered_per_team == 13
    assert s.replacement_rank == 131
    assert "TOV" in s.active_categories
    assert "TOV" not in LeagueSettings(punt=["TOV"]).active_categories


def test_minutes_parsing():
    assert _minutes("32:30") == 32.5
    assert _minutes(28) == 28.0


def test_eligible_positions():
    assert eligible_positions("G-F") == "PG,SG,SF,PF"
    assert eligible_positions("C") == "C"
    assert eligible_positions(None) == ""


def test_category_values_ranked(sample):
    logs, positions = sample
    v = get_player_values(logs, LeagueSettings(), SEASONS, positions=positions)
    assert v["VALUE"].is_monotonic_decreasing
    assert list(v["RANK"][:3]) == [1, 2, 3]
    # The replacement-level player is worth about zero.
    assert abs(v.sort_values("PER_GAME_VALUE", ascending=False)["VALUE"].iloc[130]) < 1e-9


def test_turnovers_count_against(sample):
    logs, positions = sample
    v = get_player_values(logs, LeagueSettings(), SEASONS, positions=positions)
    high_tov = v.loc[v["TOV"].idxmax()]
    assert high_tov["Z_TOV"] < 0


def test_punting_changes_rankings(sample):
    logs, positions = sample
    base = get_player_values(logs, LeagueSettings(), SEASONS, positions=positions)
    punt = get_player_values(logs, LeagueSettings(punt=["FT_PCT"]), SEASONS, positions=positions)
    assert list(base["PLAYER_ID"][:20]) != list(punt["PLAYER_ID"][:20])


def test_points_scoring(sample):
    logs, positions = sample
    s = LeagueSettings(scoring_type="points")
    v = get_player_values(logs, s, SEASONS, positions=positions)
    row = v.iloc[0]
    expected = sum(row[stat] * pts for stat, pts in s.point_values.items())
    assert row["FPPG"] == pytest.approx(expected)


def test_snake_order():
    d = DraftState(num_teams=10, my_slot=5)
    assert [d.team_for_pick(p) for p in (1, 5, 10, 11, 16, 20, 21)] == [1, 5, 10, 10, 5, 1, 1]
    assert d.my_pick_numbers(3) == [5, 16, 25]
    assert d.picks_until_my_turn(3) == 4


def test_open_slots_fill_specific_positions_first():
    s = LeagueSettings()
    assert open_starter_slots([{"PG", "SG"}, {"SF", "PF", "C"}], s) == ["SG", "G", "PF", "F", "C", "C", "UTIL", "UTIL"]
    assert len(open_starter_slots([], s)) == 10


def test_recommendations_exclude_drafted(sample):
    logs, positions = sample
    s = LeagueSettings()
    v = get_player_values(logs, s, SEASONS, positions=positions)
    taken = list(v["PLAYER_ID"][:12])
    recs = recommend_pick(v, DraftState(10, 5, taken), s, top_n=5)
    assert len(recs) == 5
    assert not recs["PLAYER_ID"].isin(taken).any()
    assert recs["REASONS"].str.len().gt(0).all()


# ---------------------------------------------------------------- in-season features
from datetime import date, timedelta  # noqa: E402

from engine import recent_form, rising_players, team_games, week_bounds, weekly_games_table  # noqa: E402
from make_sample_data import make_schedule  # noqa: E402


def test_shrinkage_is_light_for_full_seasons(sample):
    logs, positions = sample
    v = get_player_values(logs, LeagueSettings(), SEASONS, positions=positions)
    raw = logs[logs["SEASON"] == "2025-26"].groupby("PLAYER_ID")["PTS"].mean()
    top = v.head(5).set_index("PLAYER_ID")
    # A projection should stay close to what the player actually did, not be pulled to the middle.
    for pid, row in top.iterrows():
        assert abs(row["PTS"] - raw[pid]) / raw[pid] < 0.12


def test_one_injury_season_does_not_sink_value(sample):
    logs, positions = sample
    full = get_player_values(logs, LeagueSettings(availability_weight=0.0), SEASONS, positions=positions)
    assert list(full["PLAYER_ID"]) == list(full.sort_values("PER_GAME_VALUE", ascending=False)["PLAYER_ID"])
    v = get_player_values(logs, LeagueSettings(), SEASONS, positions=positions)
    assert v["GAMES"].min() >= 0.3 * 70   # regressed toward a normal season


def test_week_bounds_and_schedule():
    monday, sunday = week_bounds(date(2026, 10, 22))   # a Thursday
    assert monday == date(2026, 10, 19) and sunday == date(2026, 10, 25)
    sched = make_schedule()
    sched["GAME_DATE"] = pd.to_datetime(sched["GAME_DATE"]).dt.date
    counts = team_games(sched, date.today(), date.today() + timedelta(days=6))
    assert counts.sum() == 2 * ((sched["GAME_DATE"] >= date.today())
                                & (sched["GAME_DATE"] <= date.today() + timedelta(days=6))).sum()
    table = weekly_games_table(sched, date.today(), weeks=3)
    assert table.shape[1] == 3


def test_rising_players(sample):
    logs, positions = sample
    s = LeagueSettings()
    v = get_player_values(logs, s, SEASONS, positions=positions)
    form = recent_form(logs, v, s, window_days=30)
    assert {"VALUE_DELTA", "MIN_DELTA", "GP_RECENT"} <= set(form.columns)
    r = rising_players(form, top_n=5, min_minutes=0)
    assert r["VALUE_DELTA"].is_monotonic_decreasing


def test_agent_loop_with_fake_claude(sample):
    sys.path.insert(0, str(ROOT / "app"))
    import agent
    from fake_claude import FakeAnthropic
    logs, positions = sample
    s = LeagueSettings()
    v = get_player_values(logs, s, SEASONS, positions=positions)
    form = recent_form(logs, v, s, window_days=30)
    sched = make_schedule()
    sched["GAME_DATE"] = pd.to_datetime(sched["GAME_DATE"]).dt.date
    ctx = agent.Context(values=v, settings=s, form=form, schedule=sched, today=date.today(),
                        data_as_of=logs["GAME_DATE"].max().date(), my_ids=list(v["PLAYER_ID"][:3]))
    msgs = agent.run(FakeAnthropic(), "fake-model", [{"role": "user", "content": "pickups?"}], ctx)
    assert msgs[-1]["role"] == "assistant"
    tool_results = msgs[2]["content"]
    assert len(tool_results) == 2 and all(r["type"] == "tool_result" for r in tool_results)
    assert "weakest_categories" in tool_results[0]["content"]
    text, sources, activity = agent.render_parts(msgs[1]["content"])
    assert any("Searched the web" in a for a in activity)
    assert agent.render_parts(msgs[-1]["content"])[1] == [("Injury report", "https://example.com/injuries")]
    # Tool specs include the server web search tool.
    assert any(t.get("type") == "web_search_20250305" for t in agent.tool_specs())


def test_every_tool_runs(sample):
    sys.path.insert(0, str(ROOT / "app"))
    import agent
    logs, positions = sample
    s = LeagueSettings()
    v = get_player_values(logs, s, SEASONS, positions=positions)
    sched = make_schedule()
    sched["GAME_DATE"] = pd.to_datetime(sched["GAME_DATE"]).dt.date
    ctx = agent.Context(values=v, settings=s, form=recent_form(logs, v, s, 30), schedule=sched,
                        today=date.today(), data_as_of=date.today(), my_ids=list(v["PLAYER_ID"][:5]),
                        draft=DraftState(10, 5, list(v["PLAYER_ID"][:4])))
    name = v["PLAYER_NAME"].iloc[0]
    calls = {"get_player": {"name": name.lower()}, "compare_players": {"names": [name, "nobody xyz"]},
             "get_rankings": {"available_only": True, "position": "C"}, "get_my_team": {},
             "get_rising_players": {}, "get_my_slumping_players": {}, "get_schedule": {"team": "LAL"},
             "recommend_draft_pick": {}}
    assert set(calls) == set(agent.TOOLS)
    for tool, args in calls.items():
        out = agent.call_tool(ctx, tool, args)
        assert "error" not in out, (tool, out)
