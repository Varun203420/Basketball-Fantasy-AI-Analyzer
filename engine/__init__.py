"""Fantasy basketball engine: all the math. The app and the LLM only call these functions."""
from .settings import (LeagueSettings, NINE_CAT, YAHOO_DEFAULT_POINTS, YAHOO_DEFAULT_SLOTS, cat_label,
                       CURRENT_SEASON, PAST_SEASONS, ALL_SEASONS)
from .data import load_game_logs, load_positions, load_schedule, DATA_DIR
from .valuation import get_player_values, project_per_game
from .draft import DraftState, recommend_pick, open_starter_slots, team_category_totals
from .trends import recent_form, rising_players, falling_players
from .schedule import week_bounds, team_games, weekly_games_table

__all__ = [
    "LeagueSettings", "NINE_CAT", "YAHOO_DEFAULT_POINTS", "YAHOO_DEFAULT_SLOTS", "cat_label",
    "CURRENT_SEASON", "PAST_SEASONS", "ALL_SEASONS",
    "load_game_logs", "load_positions", "load_schedule", "DATA_DIR",
    "get_player_values", "project_per_game",
    "DraftState", "recommend_pick", "open_starter_slots", "team_category_totals",
    "recent_form", "rising_players", "falling_players",
    "week_bounds", "team_games", "weekly_games_table",
]
