"""Snake-draft state and pick recommendations.

The recommendation is deterministic. It starts from each player's VALUE, then:
- adds a bonus for helping our weakest categories (categories leagues, once we
  have a few players), and
- subtracts a penalty when he can't fill any open starting slot while some are
  still open.
It also flags players likely to be gone before our next pick, using our own
rankings as a stand-in for other managers.
"""
from dataclasses import dataclass, field

import pandas as pd

from .settings import SLOT_ELIGIBILITY, LeagueSettings, cat_label

NEED_BONUS = 0.15        # per z-point in a weak category
NEED_CATS = 3            # how many weakest categories count as needs
NEED_MIN_PLAYERS = 3     # roster size before category needs kick in
POSITION_PENALTY = 0.5   # value lost when only a bench spot is left for him


@dataclass
class DraftState:
    num_teams: int
    my_slot: int                                # 1-based draft position
    picks: list = field(default_factory=list)   # player ids in pick order

    @property
    def current_pick(self) -> int:
        return len(self.picks) + 1

    def team_for_pick(self, pick: int) -> int:
        rnd, pos = divmod(pick - 1, self.num_teams)
        return pos + 1 if rnd % 2 == 0 else self.num_teams - pos

    def my_pick_numbers(self, total_rounds: int) -> list[int]:
        return [p for p in range(1, total_rounds * self.num_teams + 1) if self.team_for_pick(p) == self.my_slot]

    def my_players(self) -> list:
        return [pid for i, pid in enumerate(self.picks, start=1) if self.team_for_pick(i) == self.my_slot]

    def picks_until_my_turn(self, total_rounds: int) -> int | None:
        """Picks other teams make before our next turn (0 = we're on the clock)."""
        upcoming = [p for p in self.my_pick_numbers(total_rounds) if p >= self.current_pick]
        return upcoming[0] - self.current_pick if upcoming else None

    def picks_after_next(self, total_rounds: int) -> int | None:
        """Picks other teams make between our next turn and the one after it."""
        upcoming = [p for p in self.my_pick_numbers(total_rounds) if p >= self.current_pick]
        return upcoming[1] - upcoming[0] - 1 if len(upcoming) > 1 else None


def _positions(value) -> set:
    return {p.strip() for p in str(value or "").split(",") if p.strip()}


def starter_slots(settings: LeagueSettings) -> list[str]:
    return [slot for slot, n in settings.roster_slots.items() if slot in SLOT_ELIGIBILITY for _ in range(n)]


def max_starters_filled(players_positions: list[set], slots: list[str]) -> int:
    """Maximum number of starting slots these players can fill (bipartite matching)."""
    match = [-1] * len(slots)

    def try_assign(i, seen):
        for j, slot in enumerate(slots):
            if j in seen or not (players_positions[i] & SLOT_ELIGIBILITY[slot]):
                continue
            seen.add(j)
            if match[j] == -1 or try_assign(match[j], seen):
                match[j] = i
                return True
        return False

    return sum(try_assign(i, set()) for i in range(len(players_positions)))


FLEX_ORDER = {"G": 1, "F": 1, "UTIL": 2}   # flexible slots are left open last


def open_starter_slots(roster_positions: list[set], settings: LeagueSettings) -> list[str]:
    """Starting slots still empty, filling specific positions before flexible ones.

    Slots are matched in priority order with augmenting paths; a slot that gets
    matched stays matched, so PG/SG/SF/PF/C fill first and G/F/UTIL stay open."""
    slots = sorted(starter_slots(settings), key=lambda s: FLEX_ORDER.get(s, 0))
    owner = [-1] * len(roster_positions)   # player index -> slot index

    def try_fill(j, seen):
        for i, pos in enumerate(roster_positions):
            if i in seen or not (pos & SLOT_ELIGIBILITY[slots[j]]):
                continue
            seen.add(i)
            if owner[i] == -1 or try_fill(owner[i], seen):
                owner[i] = j
                return True
        return False

    filled = {j for j in range(len(slots)) if try_fill(j, set())}
    order = starter_slots(settings)
    open_slots = [slots[j] for j in range(len(slots)) if j not in filled]
    return sorted(open_slots, key=order.index)


def team_category_totals(values: pd.DataFrame, my_ids: list, settings: LeagueSettings) -> pd.Series:
    zcols = ["Z_" + c for c in settings.active_categories]
    mine = values[values["PLAYER_ID"].isin(my_ids)]
    return mine[zcols].sum() if len(mine) else pd.Series(0.0, index=zcols)


def recommend_pick(
    values: pd.DataFrame,
    draft: DraftState,
    settings: LeagueSettings,
    top_n: int = 10,
) -> pd.DataFrame:
    """Top available players for us right now, with a SCORE and plain-language REASONS."""
    rounds = settings.rostered_per_team
    available = values[~values["PLAYER_ID"].isin(draft.picks)].copy()
    my_ids = draft.my_players()
    mine = values[values["PLAYER_ID"].isin(my_ids)]
    roster_positions = [_positions(p) for p in mine["POSITIONS"]]
    slots = starter_slots(settings)
    filled_now = max_starters_filled(roster_positions, slots)
    starters_open = filled_now < len(slots)
    have_positions = available["POSITIONS"].astype(str).str.len().gt(0).any()

    weak = []
    if settings.scoring_type == "categories" and len(my_ids) >= NEED_MIN_PLAYERS:
        weak = list(team_category_totals(values, my_ids, settings).nsmallest(NEED_CATS).index)

    gone_window = draft.picks_until_my_turn(rounds)
    if gone_window == 0:
        gone_window = draft.picks_after_next(rounds)
    available["AVAIL_RANK"] = range(1, len(available) + 1)

    scores, reasons = [], []
    for _, p in available.iterrows():
        score, why = p["VALUE"], []
        if weak:
            help_z = sum(max(0.0, p[c]) for c in weak)
            score += NEED_BONUS * help_z * p["GAMES"] / 82
            helped = [cat_label(c[2:]) for c in weak if p[c] > 0.5]
            if helped:
                why.append("helps our weak categories: " + ", ".join(helped))
        if have_positions and starters_open:
            fills = max_starters_filled(roster_positions + [_positions(p["POSITIONS"])], slots) > filled_now
            if not fills:
                score -= POSITION_PENALTY
                why.append("would only fill a bench spot")
        if settings.scoring_type == "categories":
            zs = {c: p["Z_" + c] for c in settings.active_categories}
            best = sorted(zs, key=zs.get, reverse=True)[:3]
            why.insert(0, "strong in " + ", ".join(cat_label(c) for c in best if zs[c] > 0.5) if any(zs[c] > 0.5 for c in best) else "balanced profile")
            worst = [c for c in zs if zs[c] < -1.0]
            if worst:
                why.append("hurts " + ", ".join(cat_label(c) for c in worst))
        else:
            why.insert(0, f"{p['FPPG']:.1f} fantasy pts/game")
        if p["GAMES"] < 60:
            why.append(f"availability risk (~{p['GAMES']:.0f} games projected)")
        scores.append(score)
        reasons.append("; ".join(why))

    available["SCORE"] = scores
    available["REASONS"] = reasons
    available = available.sort_values("SCORE", ascending=False)
    if gone_window is not None:
        available["LIKELY_GONE"] = available["AVAIL_RANK"] <= gone_window
    else:
        available["LIKELY_GONE"] = False
    return available.head(top_n).reset_index(drop=True)
