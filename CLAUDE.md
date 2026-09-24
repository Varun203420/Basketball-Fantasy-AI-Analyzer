# CLAUDE.md

Shared context for anyone (human or Claude) working in this repo. Read this first, then `docs/design.md`.

## Project

An AI assistant for fantasy basketball: draft help first, then waiver pickups and trade analysis.
A deterministic stats engine does all the math. An LLM agent calls the engine as tools and explains
recommendations in plain language. The LLM never computes player values itself.

**Target format:** Yahoo, points leagues. Category leagues and other platforms come later.
**MVP:** a draft assistant usable in a real draft this October.

## Repo layout

- `engine/` — data pipeline, database, valuation (projected fantasy points per game, games played,
  value over replacement), projections, backtests
- `app/` — FastAPI backend, AI agent (tools, prompts), UI
- `docs/design.md` — design doc, interface contract, milestones, decision log
- `CLAUDE.md` — this file

## Ownership

- Engine (`engine/`): collaborator (data science)
- App and agent (`app/`): Varun
- Interface contract and design doc: both

## Interface contract

`app/` talks to `engine/` only through these functions (full details in `docs/design.md`):

- `get_player_values(league_settings)`
- `recommend_pick(draft_state, roster, league_settings)`
- `get_player_profile(player_id)`
- `find_pickups(roster, free_agents, week)` (post-MVP)
- `evaluate_trade(players_out, players_in, roster)` (post-MVP)

Shared data objects: `LeagueSettings`, `Player`, `DraftState`, `Roster`.

## Rules

- Do not change a contract function's signature or return shape without updating `docs/design.md`
  in the same pull request, and flag it in the PR title.
- `app/` code may use mock engine functions that return the same shapes until the real engine is ready.
- The live draft pick path is deterministic: the engine picks, the LLM only writes the explanation.
- The agent layer is a single agent with tools, not multi-agent.
- New project decisions go in the decision log in `docs/design.md` with a one-line reason.
- Work on branches; merge through pull requests.

## Conventions

- Python for engine and backend.
- Keep secrets (API keys, Yahoo OAuth credentials) in `.env`, never committed.
