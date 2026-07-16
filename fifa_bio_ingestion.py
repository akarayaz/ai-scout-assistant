"""
fifa_bio_ingestion.py

Pulls birth date, nationality, and preferred foot for Premier League
players from the FIFA 16 Kaggle dataset (players_16.csv) and writes
them into the `players` table.

Tries a direct name match (short_name / long_name) first. Unmatched
players get fuzzy-match suggestions printed out but NOT applied
automatically - review these manually and fix via SQL if needed, to
avoid mismatching two different players.

Usage:
    python fifa_bio_ingestion.py
"""

import difflib

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql://scout:scout_dev_password@localhost:5432/ai_scout"
CSV_PATH = "players_16.csv"


def get_engine():
    return create_engine(DB_URL)


def main():
    fifa = pd.read_csv(CSV_PATH)

    pl = fifa[fifa["league_name"] == "English Premier League"].copy()
    print(f"Found {len(pl)} Premier League players in FIFA 16.")

    engine = get_engine()
    with engine.begin() as conn:
        our_players = pd.read_sql(text("SELECT player FROM players"), conn)["player"].tolist()

    by_short = {row["short_name"]: row for _, row in pl.iterrows()}
    by_long = {row["long_name"]: row for _, row in pl.iterrows()}

    # Second pool: the full FIFA dataset (for mid-season transfers/loans -
    # they may show up under a different league/club in FIFA's September
    # 2015 snapshot)
    by_short_all = {row["short_name"]: row for _, row in fifa.iterrows()}
    by_long_all = {row["long_name"]: row for _, row in fifa.iterrows()}

    matched_rows = []
    unmatched = []

    for player in our_players:
        row = by_short.get(player) or by_long.get(player)
        if row is None:
            row = by_short_all.get(player) or by_long_all.get(player)
        if row is not None:
            matched_rows.append((player, row))
        else:
            unmatched.append(player)

    print(f"\nDirect matches: {len(matched_rows)}/{len(our_players)}")
    print(f"Unmatched: {len(unmatched)}")

    if unmatched:
        print("\nFuzzy-match suggestions (NOT applied automatically, review manually):")
        # Search the entire FIFA dataset (not just PL) - mid-season
        # transfer/loan players may appear under a different club/league
        all_fifa_names = fifa["short_name"].tolist() + fifa["long_name"].tolist()
        for name in unmatched:
            close = difflib.get_close_matches(name, all_fifa_names, n=3, cutoff=0.7)
            print(f"  {name}  ->  {close}")

    with engine.begin() as conn:
        for player, row in matched_rows:
            conn.execute(
                text(
                    """
                    UPDATE players
                    SET birth_date = :dob,
                        nationality = :nationality,
                        preferred_foot = :foot,
                        source = 'fifa16'
                    WHERE player = :player
                    """
                ),
                {
                    "dob": row["dob"],
                    "nationality": row["nationality"],
                    "foot": row["preferred_foot"],
                    "player": player,
                },
            )

    print(f"\n{len(matched_rows)} players updated in the database.")


if __name__ == "__main__":
    main()
