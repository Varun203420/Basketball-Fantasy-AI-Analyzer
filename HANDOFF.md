# Handoff: where the project stands

Last updated: Oct 19, 2026. Read `CLAUDE.md` first, then this.

## Where we are

The experiment league drafted Oct 18 (without the app). Focus is now **in-season decisions**: pickups, injuries, schedule, trends. The 2026-27 season starts this week.

## What's built

| Piece | File | Status |
| --- | --- | --- |
| League settings (9-cat or points, punts, roster, injury-risk weight) | `engine/settings.py` | Done |
| Data pull: game logs (3 seasons), schedule, positions | `engine/data.py`, `scripts/pull_data.py` | Game logs + positions verified on Varun's laptop; **schedule pull not yet run** |
| Projections + values | `engine/valuation.py` | Done; checked against real 2024-26 data |
| Rising / falling players | `engine/trends.py` | Done; checked on real data |
| Schedule (games per team per week) | `engine/schedule.py` | Done on sample data |
| Draft board + recommendations | `engine/draft.py`, Draft tab | Done |
| Chat assistant (tools + web search) | `app/agent.py`, Assistant tab | Tested with a fake Claude; **not yet run with a real key** |
| Streamlit app (6 tabs) | `app/streamlit_app.py` | Clicked through on sample and real data |

## How values work

1. **Projection.** Per-game stats blend the current season and the last two (weights 1.0 / 0.6 / 0.3, each multiplied by games played, so a few early-season games barely move it). Light shrinkage toward a typical rotation player (8 games' worth), which only matters for small samples.
2. **Games.** From the last two completed seasons (60/40), regressed 30% toward 70 games so one injury year doesn't sink a star.
3. **Categories.** Per-game z-score per category against the draftable pool. FG%/FT% volume-weighted, turnovers negative, punts skipped. Points leagues use fantasy points per game.
4. **Value.** (per-game value − replacement level) × (1 − w + w × games/82), where w is the injury-risk weight (default 0.5).
5. **Trends.** Each recent game is valued on the same scale; recent average minus projection = rising/falling.

Oct 19 fix: an earlier version shrank everyone ~20% toward average and over-penalized one injury season (Giannis ranked 67th). Fixed; on real data the top is Jokić, SGA, Wembanyama, Maxey, Kawhi, Luka. Giannis is 54th in 9-cat because of FT% (5th with FT% punted), which matches how 9-cat sites rank him.

## The assistant

`app/agent.py` gives Claude these tools: `get_player`, `compare_players`, `get_rankings`, `get_my_team`, `get_rising_players`, `get_my_slumping_players`, `get_schedule`, `recommend_draft_pick`, plus Anthropic's server-side `web_search` for injury news. The system prompt forbids inventing numbers. Default model `claude-sonnet-5-5` (override with `ANTHROPIC_MODEL` in `.env`). History is trimmed to the last 6 turns to bound cost.

## Next steps

1. **Run `python scripts/pull_data.py --daily`** to get the 2026-27 schedule (and games once the season starts). Rerun daily.
2. **Try the assistant with a real key**: enter the roster in My team, then ask the quick-prompt questions. Note bad answers in `docs/assistant-notes.md`.
3. **Yahoo sync** (Varun): roster, free agents, and league settings from the Yahoo Fantasy API, replacing manual roster entry. Biggest usability gain.
4. **Backtest the weights** (Mahir): project 2025-26 from 2024-25 and 2023-24 and compare with actual results; tune `SEASON_WEIGHTS`, `GAMES_REGRESSION`, `SHRINK_GAMES`. Also test whether minutes trends predict future value.
5. **Teammate dependency** (Mahir): with/without splits for key teammates, feeding the injury-return logic in pickups.
6. **Weekly matchup planner**: compare our projected category totals against this week's opponent, using games left.

## Known limitations

- Rookies with no NBA games are missing from rankings.
- "Available" means not on our roster and not marked as taken in the app; until Yahoo sync, the assistant asks the user to confirm.
- Positions are a rough mapping from NBA.com (G → PG,SG); fix key players in `data/overrides.csv`.
- Trends use the latest games in the data; until 2026-27 games are pulled, they reflect last April.
