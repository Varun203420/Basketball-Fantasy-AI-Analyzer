"""Schedule helpers: games per team in a fantasy week (Monday to Sunday)."""
from datetime import date, timedelta

import pandas as pd


def week_bounds(day: date) -> tuple[date, date]:
    """Monday and Sunday of the fantasy week containing `day` (Yahoo weeks run Mon-Sun)."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def team_games(schedule: pd.DataFrame, start: date, end: date) -> pd.Series:
    """Number of games each team plays from start to end, inclusive."""
    s = schedule[(schedule["GAME_DATE"] >= start) & (schedule["GAME_DATE"] <= end)]
    counts = pd.concat([s["HOME"], s["AWAY"]]).value_counts()
    return counts.sort_values(ascending=False)


def team_game_dates(schedule: pd.DataFrame, team: str, start: date, end: date) -> list[date]:
    s = schedule[(schedule["GAME_DATE"] >= start) & (schedule["GAME_DATE"] <= end)]
    return sorted(s.loc[(s["HOME"] == team) | (s["AWAY"] == team), "GAME_DATE"].tolist())


def weekly_games_table(schedule: pd.DataFrame, today: date, weeks: int = 3) -> pd.DataFrame:
    """Teams x upcoming weeks: games per week, starting with the current week."""
    cols = {}
    monday, _ = week_bounds(today)
    for i in range(weeks):
        start = monday + timedelta(weeks=i)
        end = start + timedelta(days=6)
        label = "Rest of this week" if i == 0 else f"Week of {start:%b %d}"
        cols[label] = team_games(schedule, max(start, today) if i == 0 else start, end)
    table = pd.DataFrame(cols).fillna(0).astype(int)
    return table.sort_values(list(table.columns), ascending=False)
