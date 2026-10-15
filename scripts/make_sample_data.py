"""Generate fake game logs in data/sample/ with the same columns as nba_api.

Lets the app and tests run without NBA.com access. Players are fictional
("Sample Player 001"); the numbers are realistic in shape, not real.

    python scripts/make_sample_data.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sample"
SEASONS = ["2025-26", "2024-25"]
TEAMS = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM",
         "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]
POSITIONS = ["G", "G", "G-F", "F", "F", "F-C", "C", "C-F", "F-G"]


def make(n_players: int = 260, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    rows, pos_rows = [], []
    for i in range(n_players):
        pid = 1_000_000 + i
        name = f"Sample Player {i + 1:03d}"
        pos = POSITIONS[i % len(POSITIONS)]
        team = TEAMS[i % len(TEAMS)]
        pos_rows.append({"PLAYER_ID": pid, "NBA_POSITION": pos})
        big = "C" in pos
        guard = pos.startswith("G")
        skill = rng.gamma(2.2, 0.45)
        per36 = {
            "PTS": 11 + 9 * skill, "REB": (9 if big else 4.5) + 2 * skill, "AST": (5.5 if guard else 2) + 1.5 * skill,
            "STL": 0.8 + 0.4 * rng.random(), "BLK": (1.4 if big else 0.4) + 0.4 * rng.random(),
            "FG3M": (0.6 if big else 1.9) + rng.random(), "TOV": 1.3 + 0.6 * skill,
        }
        fg_pct = (0.56 if big else 0.45) + rng.normal(0, 0.03)
        ft_pct = (0.70 if big else 0.80) + rng.normal(0, 0.06)
        injury_prone = rng.random() < 0.2
        for s_idx, season in enumerate(SEASONS):
            mpg = float(np.clip(14 + 20 * min(skill, 1.6) / 1.6 + rng.normal(0, 3), 8, 37))
            gp = int(rng.integers(30, 62) if injury_prone else rng.integers(62, 82))
            for g in range(gp):
                mins = max(0.0, rng.normal(mpg, 4))
                scale = mins / 36
                line = {k: int(rng.poisson(max(v * scale, 0.01))) for k, v in per36.items()}
                fga = max(line["PTS"] // 2, line["FG3M"], 1)
                fgm = min(fga, int(rng.binomial(fga, np.clip(fg_pct, 0.3, 0.7))))
                fta = int(rng.poisson(max(per36["PTS"] * 0.22 * scale, 0.01)))
                ftm = int(rng.binomial(fta, np.clip(ft_pct, 0.4, 0.95))) if fta else 0
                rows.append({
                    "SEASON_ID": "2" + season[:4], "PLAYER_ID": pid, "PLAYER_NAME": name,
                    "TEAM_ABBREVIATION": team, "GAME_ID": f"{s_idx}{g:05d}",
                    "GAME_DATE": (pd.Timestamp(f"{season[:4]}-10-22") + pd.Timedelta(days=2 * g)).date().isoformat(),
                    "MIN": round(mins, 1), "FGM": fgm, "FGA": fga, "FTM": ftm, "FTA": fta, **line, "SEASON": season,
                })
    return pd.DataFrame(rows), pd.DataFrame(pos_rows)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    logs, positions = make()
    for season in SEASONS:
        logs[logs["SEASON"] == season].to_csv(OUT / f"game_logs_{season}.csv", index=False)
    positions.to_csv(OUT / "positions.csv", index=False)
    print(f"Wrote {len(logs):,} sample game rows to {OUT}")
    sys.exit(0)
