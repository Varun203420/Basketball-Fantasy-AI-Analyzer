# Basketball Fantasy AI Analyzer

A fantasy basketball draft assistant. A stats engine ranks players (9-category or points leagues) and recommends picks during a snake draft; Claude explains the recommendation in plain language.

## Run it (Windows PowerShell)

```powershell
cd ~\Documents\Basketball-Fantasy-AI-Analyzer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Real NBA data (run on your own laptop; takes a minute)
python scripts/pull_data.py

# Or fake data, just to try the app
python scripts/make_sample_data.py

streamlit run app/streamlit_app.py
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

For Claude explanations, create a `.env` file in the repo root containing `ANTHROPIC_API_KEY=your-key`. The app works without it.

Run the tests with `pytest`.

## Using the app in a draft

1. In the sidebar, set the number of teams, your draft position, and the scoring format (punt categories if you want).
2. Each time anyone picks, click **Draft** next to that player or find them under **Record any pick**. Picks are assigned to whichever team is on the clock in snake order.
3. The top of the page shows who's on the clock and how many picks until yours. Recommendations marked ⚠️ are likely gone before your next turn.
4. Made a mistake? **Undo last pick**.

To hand-correct a player (injury, trade, Yahoo position eligibility), copy `data/overrides.example.csv` to `data/overrides.csv` and edit it.

## Layout

- `engine/` all math: settings, data pull, projections and values, draft logic
- `app/` Streamlit UI and the Claude explanation call
- `scripts/` data pull and sample-data generator
- `tests/` engine tests on fake data
- `docs/design.md` design doc and decision log; `HANDOFF.md` current status and next steps
