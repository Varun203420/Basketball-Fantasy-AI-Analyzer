# CLAUDE.md

Shared context for anyone (human or Claude) working in this repo. Read this first, then `docs/design.md`.

## Project

An AI assistant for fantasy basketball: draft help first, then waiver pickups and trade analysis.
A deterministic stats engine does all the math. An LLM (Claude API) explains recommendations in
plain language. The LLM never computes player values itself.

**Leagues:** our homegrown league (Yahoo points, drafted Oct 1) stays tool-free. The app is for an
experimental league whose draft is **Sunday, Oct 18, 2026**. Its exact settings don't matter; the
app defaults to 10 teams, head-to-head 9-category, Yahoo default roster (13 + 2 IL), and everything
is editable in the sidebar. Points scoring is also supported.

## Current status

See `HANDOFF.md` for what's built, what's untested, and the ordered task list. In short: engine,
draft logic, and the Streamlit draft board work on fake data; the real NBA data pull and the Claude
call haven't been run yet. Pickups, trades, backtesting, and FastAPI come after Sunday's draft.

## Repo layout

- `engine/` data pipeline, valuation, projections (later: backtests, pickups)
- `app/` Streamlit UI and Claude API calls (later: FastAPI backend, pickup agent)
- `docs/design.md` design doc, interface contract, milestones, decision log
- `CLAUDE.md` this file

## Ownership

- Engine (`engine/`): Mahir Krishnan (data science)
- App (`app/`): Varun Hariharan
- Interface contract and design doc: both

## Interface contract

`app/` calls `engine/` only through these functions (details in `docs/design.md`). For the MVP,
Streamlit imports them directly; after the draft a FastAPI backend will expose the same functions.

- `get_player_values(logs, settings, seasons, positions=None, overrides=None)` — built
- `recommend_pick(values, draft_state, settings, top_n=10)` — built (roster comes from `DraftState`)
- `get_player_profile(player_id)` — not built yet
- `find_pickups(roster, free_agents, week)` — after draft
- `evaluate_trade(players_out, players_in, roster)` — after draft

Shared data objects: `LeagueSettings` (`engine/settings.py`) and `DraftState` (`engine/draft.py`).
Players are rows of the values DataFrame (columns include `PLAYER_ID`, `PLAYER_NAME`, `POSITIONS`,
`GAMES`, `VALUE`, and `Z_<category>` or `FPPG`).

## Commands

- `pip install -r requirements.txt`
- `python scripts/pull_data.py` (real data, run on a laptop) or `python scripts/make_sample_data.py`
- `streamlit run app/streamlit_app.py`
- `pytest`

## Rules

- Don't change a contract function's signature or return shape without updating `docs/design.md` in
  the same pull request, and flag it in the PR title.
- `app/` may use mock engine functions returning the same shapes until the real engine is ready.
- The draft pick is deterministic: the engine ranks, the LLM only explains.
- Single agent with tools, not multi-agent (for post-draft agent features).
- New decisions go in the decision log in `docs/design.md` with a one-line reason.
- Work on branches; merge through pull requests.

## Conventions

- Python for everything in the MVP.
- Secrets (Anthropic API key, later Yahoo OAuth credentials) go in `.env`, never committed.
