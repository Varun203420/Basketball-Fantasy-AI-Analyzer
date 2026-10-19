"""League settings: scoring format and roster shape.

Placeholder defaults: 10-team head-to-head 9-category league with Yahoo's default
roster. Everything here is editable in the app sidebar.
"""
from dataclasses import dataclass, field

NINE_CAT = ["PTS", "REB", "AST", "STL", "BLK", "FG3M", "FG_PCT", "FT_PCT", "TOV"]
LOWER_IS_BETTER = {"TOV"}
CAT_LABELS = {"FG3M": "3PM", "FG_PCT": "FG%", "FT_PCT": "FT%", "TOV": "TO"}

# Yahoo's default NBA points scoring, used when scoring_type == "points".
YAHOO_DEFAULT_POINTS = {"PTS": 1.0, "REB": 1.2, "AST": 1.5, "STL": 3.0, "BLK": 3.0, "TOV": -1.0}

# Yahoo default roster: 10 starters + 3 bench = 13, plus 2 IL.
YAHOO_DEFAULT_SLOTS = {
    "PG": 1, "SG": 1, "G": 1, "SF": 1, "PF": 1, "F": 1,
    "C": 2, "UTIL": 2, "BN": 3, "IL": 2,
}

# Which positions can fill each slot.
SLOT_ELIGIBILITY = {
    "PG": {"PG"}, "SG": {"SG"}, "G": {"PG", "SG"},
    "SF": {"SF"}, "PF": {"PF"}, "F": {"SF", "PF"},
    "C": {"C"}, "UTIL": {"PG", "SG", "SF", "PF", "C"},
}


# Seasons the engine uses. CURRENT_SEASON may have few or no games yet; it feeds
# per-game projections (weighted by games played) and recent-form trends.
CURRENT_SEASON = "2026-27"
PAST_SEASONS = ["2025-26", "2024-25"]          # completed seasons, most recent first
ALL_SEASONS = [CURRENT_SEASON] + PAST_SEASONS


def cat_label(cat: str) -> str:
    return CAT_LABELS.get(cat, cat)


@dataclass
class LeagueSettings:
    num_teams: int = 10
    scoring_type: str = "categories"          # "categories" or "points"
    categories: list = field(default_factory=lambda: list(NINE_CAT))
    punt: list = field(default_factory=list)  # categories to ignore
    point_values: dict = field(default_factory=lambda: dict(YAHOO_DEFAULT_POINTS))
    roster_slots: dict = field(default_factory=lambda: dict(YAHOO_DEFAULT_SLOTS))
    # How much projected missed games reduce value: 0 = rank purely per game,
    # 1 = scale fully by projected games / 82.
    availability_weight: float = 0.5

    @property
    def active_categories(self) -> list:
        return [c for c in self.categories if c not in self.punt]

    @property
    def rostered_per_team(self) -> int:
        """Players each team drafts (IL slots are filled later, not at the draft)."""
        return sum(n for slot, n in self.roster_slots.items() if slot != "IL")

    @property
    def replacement_rank(self) -> int:
        """Rank of the best player left undrafted once every roster is full."""
        return self.num_teams * self.rostered_per_team + 1
