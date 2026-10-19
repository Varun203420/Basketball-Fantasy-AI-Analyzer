# CLAUDE.md

Shared context for anyone (human or Claude) working in this repo. Read this first, then `docs/design.md`.

## Project

An AI assistant for fantasy basketball: draft, waiver pickups, injuries, schedule, and trades.
A deterministic stats engine does all the math. A Claude chat assistant (`app/agent.py`) calls engine
functions as tools and uses web search for injury news. The LLM never computes player values itself.

**Leagues:** our homegrown league (Yahoo points) stays tool-free. The app is for an experimental
league (drafted Oct 18, 2026). Its exact settings don't matter; the app defaults to 10 teams,
head-to-head 9-category, Yahoo default roster (13 + 2 IL), all editable in the sidebar. Points
scoring is also supported.

## Current status

See `HANDOFF.md` for what's built, what's untested, how values work, and the ordered task list.
Focus is in-season: the Assistant, My team, Trending, and Schedule tabs.

## Repo layout

- `engine/` data pull, valuation/projections, draft logic, trends (rising players), schedule
- `app/streamlit_app.py` UI; `app/agent.py` chat assistant (tool definitions, system prompt, loop)
- `docs/design.md` design doc, interface contract, milestones, decision log
- `CLAUDE.md` this file

## Ownership

- Engine (`engine/`): Mahir Krishnan (data science)
- App (`app/`): Varun Hariharan
- Interface contract and design doc: both

## Interface contract

`app/` calls `engine/` only through these functions (details in `docs/design.md`). Streamlit
imports them directly; a FastAPI backend may expose the same functions later.

- `get_player_values(logs, settings, seasons=None, positions=None, overrides=None)` — built
- `recommend_pick(values, draft_state, settings, top_n=10)` — built
- `recent_form(logs, values, settings, window_days)`, `rising_players`, `falling_players` — built
- `team_games(schedule, start, end)`, `weekly_games_table(schedule, today)` — built
- `find_pickups(roster, free_agents, week)` — next (today the agent combines rising players,
  rankings, schedule, and news itself)
- `evaluate_trade(players_out, players_in, roster)` — later

To give the assistant a new capability, add an engine function, then a tool in `app/agent.py`
(`TOOLS` dict) and a case in `tests/test_engine.py::test_every_tool_runs`.

Shared data objects: `LeagueSettings` (`engine/settings.py`) and `DraftState` (`engine/draft.py`).
Players are rows of the values DataFrame (columns include `PLAYER_ID`, `PLAYER_NAME`, `POSITIONS`,
`GAMES`, `VALUE`, and `Z_<category>` or `FPPG`).

## Commands

- `pip install -r requirements.txt`
- `python scripts/pull_data.py` (full pull, run on a laptop; NBA.com blocks cloud servers)
- `python scripts/pull_data.py --daily` (current season games + schedule)
- `python scripts/make_sample_data.py` (fake data for testing)
- `streamlit run app/streamlit_app.py`
- `pytest`

## Rules

- Don't change a contract function's signature or return shape without updating `docs/design.md` in
  the same pull request, and flag it in the PR title.
- `app/` may use mock engine functions returning the same shapes until the real engine is ready.
- The engine ranks and computes; the assistant only reasons over tool results and news. Never let
  the LLM produce stats from memory.
- Single agent with tools, not multi-agent.
- Tests must not call the real Claude API; use `tests/fake_claude.py`.
- New decisions go in the decision log in `docs/design.md` with a one-line reason.
- Work on branches; merge through pull requests.

## Conventions

- Python for everything in the MVP.
- Secrets (`ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL`, later Yahoo OAuth) go in `.env`, never committed.
