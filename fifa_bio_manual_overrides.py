"""
fifa_bio_manual_overrides.py

Applies 33 manually-reviewed correct fuzzy matches to the database
(Nordin Amrabat->Jordi Amat and Jordan Lyden->Jordan Ayew were WRONG
matches and are excluded).

Also lists South Korean players from the FIFA data so 3 well-known
players missed due to name-order differences (Son, Ki, Lee) can be
matched manually.

Usage:
    python fifa_bio_manual_overrides.py
"""

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = "postgresql://scout:scout_dev_password@localhost:5432/ai_scout"
CSV_PATH = "players_16.csv"

# StatsBomb name -> correct name found in FIFA
CONFIRMED_MATCHES = {
    "Bryan Oviedo": "B. Oviedo",
    "Steven Whittaker": "Steven Gordon Whittaker",
    "Simon Mignolet": "S. Mignolet",
    "Mile Jedinak": "Mile Jedinák",
    "Andre Green": "André Green",
    "Robert Brady": "Robbie Brady",
    "Steven Naismith": "Steven John Naismith",
    "David de Gea Quintana": "David De Gea Quintana",
    "Siem Stefan de Jong": "Siem de Jong",
    "Gary O''Neil": "Gary O'Neil",
    "N''Golo Kanté": "N'Golo Kanté",
    "Tim Howard": "T. Howard",
    "Eunan O''Kane": "Eunan O'Kane",
    "Bafétimbi Gomis": "Bafétimbi Fredius Gomis",
    "Danny Drinkwater": "D. Drinkwater",
    "Allan Romeo Nyom": "Allan-Roméo Nyom",
    "Clinton Mua N''Jie": "Clinton Mua N'Jie",
    "Francis Joseph Coquelin": "Francis Coquelin",
    "Fernando Luiz Roza": "Fernando Luiz Rosa",
    "John O''Shea": "John O'Shea",
    "James Grant Chester": "James Chester",
    "Matt Grimes": "Matthew Grimes",
    "Maya Yoshida": "M. Yoshida",
    "Younes Kaboul": "Younès Kaboul",
    "Yann Gérard M''Vila": "Yann Gérard M'Vila",
    "Raheem Sterling": "R. Sterling",
    "Jermain Defoe": "Jermain Colin Defoe",
    "Vincent Kompany": "Vincent Jean Mpoy Kompany",
    "Shinji Okazaki": "S. Okazaki",
    'Charles N"Zogbia': "Charles N'Zogbia",
    "Jan Vertonghen": "J. Vertonghen",
    "Pape N''Diaye Souaré": "Pape N'Diaye Souaré",
    "Sung-Yeung Ki": "Ki Sung Yueng",
    "Chung-Yong Lee": "Lee Chung Yong",
}


def main():
    fifa = pd.read_csv(CSV_PATH)
    by_name = {}
    for _, row in fifa.iterrows():
        by_name[row["short_name"]] = row
        by_name[row["long_name"]] = row
 
    engine = create_engine(DB_URL)
 
    applied, missing = 0, []
    with engine.begin() as conn:
        for our_name, fifa_name in CONFIRMED_MATCHES.items():
            row = by_name.get(fifa_name)
            if row is None:
                missing.append((our_name, fifa_name))
                continue
            conn.execute(
                text(
                    """
                    UPDATE players
                    SET birth_date = :dob,
                        nationality = :nationality,
                        preferred_foot = :foot,
                        source = 'fifa16_manual'
                    WHERE player = :player
                    """
                ),
                {
                    "dob": row["dob"],
                    "nationality": row["nationality"],
                    "foot": row["preferred_foot"],
                    "player": our_name,
                },
            )
            applied += 1
 
    print(f"{applied} manual matches applied.")
    if missing:
        print("Not found in FIFA data (check these):", missing)


if __name__ == "__main__":
    main()