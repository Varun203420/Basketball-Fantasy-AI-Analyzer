# Basketball Fantasy AI Analyzer

A fantasy basketball assistant. A stats engine ranks players (9-category or points leagues), tracks recent form and the schedule, and runs a snake-draft board. A Claude-powered chat assistant answers questions using the engine's numbers plus live injury news from web search.

## Run it (Windows PowerShell)

```powershell
cd ~\Documents\Basketball-Fantasy-AI-Analyzer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python scripts/pull_data.py          # first time: 3 seasons of games, schedule, positions
python scripts/pull_data.py --daily  # during the season: refresh this season's games + schedule

streamlit run app/streamlit_app.py
```

No NBA access? `python scripts/make_sample_data.py` creates fake players so you can try the app.

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

For the assistant, create a `.env` file in the repo folder with one line: `ANTHROPIC_API_KEY=your-key`. Optionally add `ANTHROPIC_MODEL=...` to change the model.

Run the tests with `pytest`.

## Tabs

- **Assistant**: chat about pickups, trades, injuries, and matchups. It calls engine tools (rankings, player profiles, your team, rising players, schedule) and searches the web for news, with sources.
- **My team**: enter your roster (and optionally players on other teams), see category strengths, open slots, and games left this week.
- **Trending**: players playing above or below their projection over the last 7/14/30 days.
- **Schedule**: games per team for the rest of this week and the next two.
- **Draft**: snake-draft board with recommendations and a "likely gone" flag.
- **Rankings**: full table with per-category z-scores.

Sidebar: teams, scoring (categories with optional punts, or points), and an injury-risk weight (0 ranks purely per game; 1 fully scales by projected games).

To hand-correct a player (injury, trade, Yahoo position eligibility), copy `data/overrides.example.csv` to `data/overrides.csv` and edit it.

## Layout

- `engine/` all math: settings, data pull, projections and values, draft logic, trends, schedule
- `app/` Streamlit UI (`streamlit_app.py`) and the chat agent (`agent.py`)
- `scripts/` data pull and sample-data generator
- `tests/` tests on fake data, including the chat loop with a fake Claude
- `docs/design.md` design doc and decision log; `HANDOFF.md` current status and next steps
