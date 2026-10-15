# Handoff: where the project stands

Last updated: Oct 15, 2026. Read `CLAUDE.md` first, then this.

## Goal right now

Use the app in our experimental league's draft on **Sunday, Oct 18**. Our homegrown league stays tool-free. The experiment league's exact settings don't matter much; the app defaults to a 10-team, 9-category league and everything is changeable in the sidebar.

## What's built

| Piece | File | Status |
| --- | --- | --- |
| League settings (9-cat or points, punts, Yahoo roster) | `engine/settings.py` | Done, tested |
| NBA data pull via `nba_api` | `engine/data.py`, `scripts/pull_data.py` | Written, **not yet run against NBA.com** |
| Fake data for testing | `scripts/make_sample_data.py` | Done |
| Projections + values (z-scores, points) | `engine/valuation.py` | Done, tested on fake data |
| Snake draft logic + recommendations | `engine/draft.py` | Done, tested |
| Streamlit draft board | `app/streamlit_app.py` | Done, clicked through a full draft headlessly |
| Claude explanation | `app/llm.py` | Written, **not yet called with a real key** |

## How values work

1. **Projection.** Per-game stats are a blend of the last two seasons (70/30 by games played), shrunk toward a typical rotation player when the sample is small. Projected games blend the last two seasons' games played.
2. **Categories.** Per-game z-score in each category against the draftable pool (top 130 players). FG% and FT% are volume-weighted; turnovers count negatively; punted categories are skipped.
3. **Value.** (per-game value − replacement level) × projected games / 82.
4. **Recommendation.** Value, plus a bonus for our weakest categories once we have 3+ players, minus a penalty if the player can only fill a bench spot while starting slots are open.

## Before Sunday (in order)

1. **Run the real data pull** on a laptop: `python scripts/pull_data.py`. If NBA.com times out, wait and retry; it rate-limits. Confirm `data/game_logs_2025-26.csv`, `data/game_logs_2024-25.csv`, and `data/positions.csv` exist.
2. **Sanity-check the top 150** in the app's "All rankings" panel. Look for players who changed teams, are injured, or are out for the season.
3. **Fix positions** for the top ~150 in `data/overrides.csv` (copy the example file). NBA.com positions are mapped roughly (G → PG,SG; F → SF,PF), and Yahoo eligibility often differs.
4. **Add the Claude key** to `.env` and click "Ask Claude to explain" once to confirm it works.
5. **Do a Yahoo mock draft** with the app open alongside it.

## Known limitations

- **Rookies and players with no NBA stats are missing.** Overrides can only edit existing players. If a rookie matters, adding him is a small change to `apply_overrides` in `engine/valuation.py`.
- **"Likely gone" uses our own rankings** as a stand-in for other managers. Yahoo ADP would be better.
- **Weights are guesses**: `SEASON_WEIGHTS`, `GAMES_WEIGHTS`, `SHRINK_GAMES` in `valuation.py`, and `NEED_BONUS`, `POSITION_PENALTY` in `draft.py`.
- The app calls the engine directly; there's no FastAPI backend yet (planned after the draft).

## After the draft (Mahir's modeling work)

1. **Backtest the weights.** Project 2024-25 from 2023-24 and 2022-23, compare against what actually happened, and tune the weights in `valuation.py`. This is the most important modeling task.
2. **Pickups.** Build `find_pickups` per the "Pickup analyzer design" section in `docs/design.md`: recent form, minutes trend, schedule, availability history, roster fit.
3. **Teammate dependency.** From game logs, compare a player's minutes and production with vs without a key teammate. Feeds the injury-return logic in pickups.
4. Then Varun adds the Claude agent with web search for injury news on top of `find_pickups`.
