# CLAUDE.md

Shared context for anyone (human or Claude) working in this repo. Read this first, then `docs/design.md`.

## Project

An AI assistant for fantasy basketball: draft help first, then waiver pickups and trade analysis.
A deterministic stats engine does all the math. An LLM (Claude API) explains recommendations in
plain language. The LLM never computes player values itself.

**League:** Yahoo, points league, Yahoo default point values. 10 teams, 13 roster spots + 2 IL.
**Deadline:** our draft is Oct 1, 2026 at 8pm PT. Until then, only work that gets a usable draft tool
ready counts. Pickups, trades, backtesting, and the FastAPI backend come after the draft.

## Current sprint (to Oct 1)

- Engine: pull last season's stats with `nba_api`, compute Yahoo fantasy points per game and games
  played, project this season, compute value over replacement for 10 teams, export a rankings CSV.
- App: Streamlit draft board. Mark players drafted, track our roster, show best available filtered by
  open roster slots. Stretch: one Claude API call to explain the top picks.
- Fallback: the rankings CSV alone must work as a cheat sheet if the app isn't ready.

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

- `get_player_values(league_settings)` — MVP
- `recommend_pick(draft_state, roster, league_settings)` — MVP
- `get_player_profile(player_id)` — MVP
- `find_pickups(roster, free_agents, week)` — after draft
- `evaluate_trade(players_out, players_in, roster)` — after draft

Shared data objects: `LeagueSettings`, `Player`, `DraftState`, `Roster`.

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
