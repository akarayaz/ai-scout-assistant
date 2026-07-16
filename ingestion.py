"""
ingestion.py

Pulls StatsBomb events (competition_id=2, season_id=27 -> Premier League
2015/2016) and writes them into Postgres's `events` and
`player_match_stats` tables.

Usage:
    python ingestion.py

Note: statsbombpy's flattened column names can vary slightly by version.
If you hit an error on first run, add this to inspect the real columns:
    print(events.columns.tolist())
"""

import json

import pandas as pd
from sqlalchemy import create_engine
from statsbombpy import sb

DB_URL = "postgresql://scout:scout_dev_password@localhost:5432/ai_scout"
COMP_ID = 2
SEASON_ID = 27

CORE_EVENT_COLS = [
    "id", "index", "period", "minute", "second", "team", "player",
    "position", "type", "possession", "possession_team", "play_pattern",
    "duration", "under_pressure",
]


def get_engine():
    return create_engine(DB_URL)


def col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return a NaN series if the column is missing, so the script doesn't break on absent fields."""
    return df[name] if name in df.columns else pd.Series([None] * len(df), index=df.index)


def split_location(df: pd.DataFrame) -> pd.DataFrame:
    if "location" in df.columns:
        df["location_x"] = df["location"].apply(
            lambda v: v[0] if isinstance(v, (list, tuple)) and len(v) > 0 else None
        )
        df["location_y"] = df["location"].apply(
            lambda v: v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else None
        )
    else:
        df["location_x"] = None
        df["location_y"] = None
    return df


def build_events_table(events: pd.DataFrame, match_id: int) -> pd.DataFrame:
    """Shape the events DataFrame for the `events` table: core fields as
    plain columns, everything else packed into the `extra` JSONB column."""
    events = split_location(events.copy())

    present_core = [c for c in CORE_EVENT_COLS if c in events.columns]
    skip_cols = set(present_core) | {"location", "location_x", "location_y"}
    extra_cols = [c for c in events.columns if c not in skip_cols]

    out = events[present_core + ["location_x", "location_y"]].copy()
    out["match_id"] = match_id
    out["extra"] = events[extra_cols].apply(
        lambda row: json.dumps(row.dropna().to_dict(), default=str), axis=1
    )
    out = out.rename(columns={"id": "event_id", "index": "event_index"})
    return out


def compute_minutes_played(events: pd.DataFrame) -> dict:
    """Simplified minutes-played calculation:
    - Starting XI players start at minute 0
    - Substitution: end time for the player going off, start time for the one coming on
    - A red card ends that player's time on the pitch at that moment
    - Everyone else is assumed to have played to the final whistle
    """
    match_end = (events["minute"] + events["second"] / 60).max()

    on_time, off_time = {}, {}

    starting_xi_rows = events[events["type"] == "Starting XI"]
    for _, row in starting_xi_rows.iterrows():
        tactics = row.get("tactics")
        if isinstance(tactics, dict):
            for p in tactics.get("lineup", []):
                name = (p.get("player") or {}).get("name")
                if name:
                    on_time[name] = 0.0

    subs = events[events["type"] == "Substitution"]
    for _, row in subs.iterrows():
        t = row["minute"] + row["second"] / 60
        player_off = row.get("player")
        player_on = row.get("substitution_replacement")
        if player_off:
            off_time[player_off] = t
        if player_on:
            on_time[player_on] = t

    for card_col in ["foul_committed_card", "bad_behaviour_card"]:
        if card_col in events.columns:
            red_rows = events[events[card_col] == "Red Card"]
            for _, row in red_rows.iterrows():
                t = row["minute"] + row["second"] / 60
                player = row.get("player")
                if player:
                    off_time[player] = t

    return {
        player: max(0.0, off_time.get(player, match_end) - on_t)
        for player, on_t in on_time.items()
    }


def compute_player_match_stats(events: pd.DataFrame, match_id: int) -> pd.DataFrame:
    minutes = compute_minutes_played(events)

    # Set of pass ids that assisted a shot (i.e. "key passes")
    key_pass_ids = set()
    if "shot_key_pass_id" in events.columns:
        key_pass_ids = set(events["shot_key_pass_id"].dropna().tolist())

    rows = []
    for player, group in events.groupby("player"):
        if not player:
            continue

        team = group["team"].iloc[0] if "team" in group.columns else None
        position = (
            group["position"].dropna().iloc[0]
            if "position" in group.columns and group["position"].notna().any()
            else None
        )

        passes = group[group["type"] == "Pass"]
        pass_outcome = col(passes, "pass_outcome")
        passes_completed = passes[pass_outcome.isna()]

        pass_cross = col(passes, "pass_cross")
        crosses = passes[pass_cross == True]  # noqa: E712
        crosses_completed = crosses[col(crosses, "pass_outcome").isna()]

        key_passes = passes[passes["id"].isin(key_pass_ids)] if "id" in passes.columns else passes.iloc[0:0]

        shots = group[group["type"] == "Shot"]
        shot_outcome = col(shots, "shot_outcome")
        shots_on_target = shots[shot_outcome.isin(["Goal", "Saved"])]
        shot_xg = col(shots, "shot_statsbomb_xg")

        duels = group[group["type"] == "Duel"]
        duel_type = col(duels, "duel_type")
        duel_outcome = col(duels, "duel_outcome")
        ground_duels = duels[duel_type == "Tackle"]
        ground_won = ground_duels[col(ground_duels, "duel_outcome").isin(
            ["Won", "Success", "Success In Play", "Success Out"]
        )]
        # aerial_duels_won/total: TODO - StatsBomb only tags the LOSING side
        # of an aerial duel ("Aerial Lost"); the winner isn't a separate
        # event. Proper counting requires matching via related_events -
        # left at 0 for now.

        dribbles = group[group["type"] == "Dribble"]
        dribble_outcome = col(dribbles, "dribble_outcome")
        dribbles_completed = dribbles[dribble_outcome == "Complete"]

        fouls_committed = group[group["type"] == "Foul Committed"]
        cards = col(fouls_committed, "foul_committed_card")

        rows.append({
            "player": player,
            "match_id": match_id,
            "team": team,
            "position": position,
            "minutes_played": round(minutes.get(player, 0.0), 1),
            "passes_attempted": len(passes),
            "passes_completed": len(passes_completed),
            "pass_accuracy": round(len(passes_completed) / len(passes), 3) if len(passes) else None,
            "progressive_passes": 0,   # TODO: needs attacking-direction normalization
            "key_passes": len(key_passes),
            "crosses_attempted": len(crosses),
            "crosses_completed": len(crosses_completed),
            "shots": len(shots),
            "shots_on_target": len(shots_on_target),
            "xg_total": float(shot_xg.sum()) if len(shot_xg) else 0.0,
            "goals": int((shot_outcome == "Goal").sum()),
            "touches_in_box": 0,       # TODO: needs attacking-direction normalization
            "progressive_carries": 0,  # TODO: needs attacking-direction normalization
            "pressures": len(group[group["type"] == "Pressure"]),
            "ball_recoveries": len(group[group["type"] == "Ball Recovery"]),
            "interceptions": len(group[group["type"] == "Interception"]),
            "ground_duels_won": len(ground_won),
            "ground_duels_total": len(ground_duels),
            "aerial_duels_won": 0,     # TODO: needs related_events matching
            "aerial_duels_total": 0,   # TODO: needs related_events matching
            "dribbles_attempted": len(dribbles),
            "dribbles_completed": len(dribbles_completed),
            "dispossessed": len(group[group["type"] == "Dispossessed"]),
            "miscontrols": len(group[group["type"] == "Miscontrol"]),
            "fouls_committed": len(fouls_committed),
            "fouls_won": len(group[group["type"] == "Foul Won"]),
            "yellow_cards": int((cards == "Yellow Card").sum()),
            "red_cards": int((cards == "Red Card").sum()),
        })

    return pd.DataFrame(rows)


def ingest_match(engine, match_id: int):
    events = sb.events(match_id=match_id)

    events_table = build_events_table(events, match_id)
    stats_table = compute_player_match_stats(events, match_id)

    events_table.to_sql("events", engine, if_exists="append", index=False)
    stats_table.to_sql("player_match_stats", engine, if_exists="append", index=False)

    print(f"Match {match_id}: wrote {len(events_table)} events, {len(stats_table)} player-match rows.")


def main():
    engine = get_engine()
    matches = sb.matches(competition_id=COMP_ID, season_id=SEASON_ID)
    print(f"Found {len(matches)} matches, starting ingestion...\n")

    ok, failed = 0, 0
    for i, match_id in enumerate(matches["match_id"], start=1):
        try:
            ingest_match(engine, match_id)
            ok += 1
        except Exception as e:
            failed += 1
            print(f"[ERROR] Match {match_id}: {e}")

        if i % 20 == 0:
            print(f"... processed {i}/{len(matches)} matches ({ok} ok, {failed} failed)\n")

    print(f"\nIngestion complete. {ok} succeeded, {failed} failed.")


if __name__ == "__main__":
    main()