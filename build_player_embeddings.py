"""
build_player_embeddings.py

Builds statistical "style" embeddings for players: takes per-90 and rate
metrics from player_season_stats, z-score normalizes them, and stores the
resulting vectors in the player_embeddings table (pgvector).

Similarity = cosine similarity between these vectors. No LLM involved -
for numeric profiles, direct feature vectors are more faithful (and
explainable) than text-embedding a generated description.

Usage:
    python build_player_embeddings.py

Note: connects as the admin user (scout), not the read-only agent role,
because it writes to player_embeddings. Re-runnable: recreates the table
each time.
"""

import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

# Admin connection (writes) - not the read-only agent role
DEFAULT_DB_URL = "postgresql://scout:scout_dev_password@localhost:5432/ai_scout"

MIN_MINUTES = 450
MODEL_NAME = "stat-vector-v1"

# All features are per-90 volumes or rates, so playing time doesn't
# dominate the vector. Order matters - it defines the vector layout.
FEATURES = [
    "passes_attempted_per90",
    "pass_accuracy",
    "key_passes_per90",
    "crosses_attempted_per90",
    "shots_per90",
    "shot_on_target_rate",
    "xg_per90",
    "goals_per90",
    "pressures_per90",
    "ball_recoveries_per90",
    "interceptions_per90",
    "ground_duels_per90",
    "ground_duel_win_rate",
    "dribbles_attempted_per90",
    "dribble_success_rate",
    "dispossessed_per90",
    "miscontrols_per90",
    "fouls_committed_per90",
    "fouls_won_per90",
]


def main():
    db_url = os.environ.get("DATABASE_URL_ADMIN", DEFAULT_DB_URL)
    engine = create_engine(db_url)

    df = pd.read_sql(
        text("SELECT * FROM player_season_stats WHERE total_minutes > :m"),
        engine,
        params={"m": MIN_MINUTES},
    )
    print(f"{len(df)} players with > {MIN_MINUTES} minutes.")

    m90 = df["total_minutes"] / 90.0
    df["passes_attempted_per90"] = df["passes_attempted"] / m90
    df["crosses_attempted_per90"] = df["crosses_attempted"] / m90
    df["shots_per90"] = df["shots"] / m90
    df["shot_on_target_rate"] = df["shots_on_target"] / df["shots"].replace(0, np.nan)
    df["ball_recoveries_per90"] = df["ball_recoveries"] / m90
    df["ground_duels_per90"] = df["ground_duels_total"] / m90
    df["dribbles_attempted_per90"] = df["dribbles_attempted"] / m90
    df["dispossessed_per90"] = df["dispossessed"] / m90
    df["miscontrols_per90"] = df["miscontrols"] / m90
    df["fouls_committed_per90"] = df["fouls_committed"] / m90
    df["fouls_won_per90"] = df["fouls_won"] / m90
    # pass_accuracy, key_passes_per90, xg_per90, goals_per90, pressures_per90,
    # interceptions_per90, ground_duel_win_rate, dribble_success_rate
    # already exist in the view.

    feats = df[FEATURES].astype(float)

    # NaN (e.g. 0 shots -> no on-target rate) -> column mean, which becomes
    # 0 after z-scoring, i.e. "neutral" on that dimension.
    feats = feats.fillna(feats.mean())

    # z-score normalize so no single metric dominates cosine distance
    feats = (feats - feats.mean()) / feats.std(ddof=0)

    dim = len(FEATURES)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS player_embeddings"))
        conn.execute(text(f"""
            CREATE TABLE player_embeddings (
                player      TEXT PRIMARY KEY REFERENCES players (player),
                embedding   vector({dim}),
                model_name  TEXT,
                updated_at  TIMESTAMPTZ DEFAULT now()
            )
        """))
        conn.execute(text("GRANT SELECT ON player_embeddings TO agent_readonly"))

        for player, row in zip(df["player"], feats.itertuples(index=False)):
            vec = "[" + ",".join(f"{v:.6f}" for v in row) + "]"
            conn.execute(
                text("""
                    INSERT INTO player_embeddings (player, embedding, model_name)
                    VALUES (:player, CAST(:vec AS vector), :model)
                """),
                {"player": player, "vec": vec, "model": MODEL_NAME},
            )

    print(f"Wrote {len(df)} embeddings ({dim} dimensions each).")

    # Sanity check: nearest neighbours for a well-known player
    probe = "N''Golo Kanté"
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT e2.player, ps.team, ps.position,
                   ROUND((1 - (e1.embedding <=> e2.embedding))::numeric, 3) AS similarity
            FROM player_embeddings e1
            JOIN player_embeddings e2 ON e2.player != e1.player
            JOIN player_season_stats ps ON ps.player = e2.player
            WHERE e1.player = :probe
            ORDER BY e1.embedding <=> e2.embedding
            LIMIT 8
        """), {"probe": probe})
        rows = result.fetchall()

    if rows:
        print(f"\nSanity check - most similar to {probe}:")
        for r in rows:
            print(f"  {r.player:30s} {str(r.team):22s} {str(r.position):26s} {r.similarity}")
    else:
        print(f"\nSanity check: '{probe}' not found (name mismatch?) - try another player.")


if __name__ == "__main__":
    main()
    