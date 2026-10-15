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
