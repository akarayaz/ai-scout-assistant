-- player_season_stats: materialized view
-- Rolls up per-match rows from player_match_stats to the
-- player-season level. Rate metrics (pass_accuracy etc.) are
-- recomputed from totals rather than averaging per-match
-- ratios - more statistically sound.

DROP MATERIALIZED VIEW IF EXISTS player_season_stats CASCADE;

CREATE MATERIALIZED VIEW player_season_stats AS
WITH team_counts AS (
    SELECT player, team, COUNT(DISTINCT match_id) AS matches_for_team
    FROM player_match_stats
    GROUP BY player, team
),
primary_team AS (
    -- For players who changed clubs mid-season, mark the club
    -- they made the most appearances for as their "primary team"
    SELECT DISTINCT ON (player) player, team
    FROM team_counts
    ORDER BY player, matches_for_team DESC
),
position_counts AS (
    SELECT player, position, COUNT(DISTINCT match_id) AS matches_at_position
    FROM player_match_stats
    WHERE position IS NOT NULL
    GROUP BY player, position
),
primary_position AS (
    -- Most-played position across the season (players sometimes
    -- appear at more than one position/role)
    SELECT DISTINCT ON (player) player, position
    FROM position_counts
    ORDER BY player, matches_at_position DESC
),
agg AS (
    SELECT
        player,
        COUNT(DISTINCT match_id)  AS appearances,
        SUM(minutes_played)       AS total_minutes,
        SUM(passes_attempted)     AS passes_attempted,
        SUM(passes_completed)     AS passes_completed,
        SUM(progressive_passes)   AS progressive_passes,
        SUM(key_passes)           AS key_passes,
        SUM(crosses_attempted)    AS crosses_attempted,
        SUM(crosses_completed)    AS crosses_completed,
        SUM(shots)                AS shots,
        SUM(shots_on_target)      AS shots_on_target,
        SUM(xg_total)             AS xg_total,
        SUM(goals)                AS goals,
        SUM(touches_in_box)       AS touches_in_box,
        SUM(progressive_carries)  AS progressive_carries,
        SUM(pressures)            AS pressures,
        SUM(ball_recoveries)      AS ball_recoveries,
        SUM(interceptions)        AS interceptions,
        SUM(ground_duels_won)     AS ground_duels_won,
        SUM(ground_duels_total)   AS ground_duels_total,
        SUM(aerial_duels_won)     AS aerial_duels_won,
        SUM(aerial_duels_total)   AS aerial_duels_total,
        SUM(dribbles_attempted)   AS dribbles_attempted,
        SUM(dribbles_completed)   AS dribbles_completed,
        SUM(dispossessed)         AS dispossessed,
        SUM(miscontrols)          AS miscontrols,
        SUM(fouls_committed)      AS fouls_committed,
        SUM(fouls_won)            AS fouls_won,
        SUM(yellow_cards)         AS yellow_cards,
        SUM(red_cards)            AS red_cards
    FROM player_match_stats
    GROUP BY player
)
SELECT
    agg.player,
    pt.team,
    pp.position,
    agg.appearances,
    ROUND(agg.total_minutes::numeric, 0)                                          AS total_minutes,
    agg.passes_attempted,
    agg.passes_completed,
    ROUND(agg.passes_completed::numeric / NULLIF(agg.passes_attempted, 0), 3)      AS pass_accuracy,
    agg.progressive_passes,
    agg.key_passes,
    ROUND((agg.key_passes * 90.0 / NULLIF(agg.total_minutes, 0))::numeric, 2)      AS key_passes_per90,
    agg.crosses_attempted,
    agg.crosses_completed,
    agg.shots,
    agg.shots_on_target,
    ROUND(agg.xg_total::numeric, 2)                                               AS xg_total,
    ROUND((agg.xg_total * 90.0 / NULLIF(agg.total_minutes, 0))::numeric, 3)        AS xg_per90,
    agg.goals,
    ROUND((agg.goals * 90.0 / NULLIF(agg.total_minutes, 0))::numeric, 3)           AS goals_per90,
    agg.touches_in_box,
    agg.progressive_carries,
    agg.pressures,
    ROUND((agg.pressures * 90.0 / NULLIF(agg.total_minutes, 0))::numeric, 2)       AS pressures_per90,
    agg.ball_recoveries,
    agg.interceptions,
    ROUND((agg.interceptions * 90.0 / NULLIF(agg.total_minutes, 0))::numeric, 2)   AS interceptions_per90,
    agg.ground_duels_won,
    agg.ground_duels_total,
    ROUND(agg.ground_duels_won::numeric / NULLIF(agg.ground_duels_total, 0), 3)    AS ground_duel_win_rate,
    agg.aerial_duels_won,
    agg.aerial_duels_total,
    agg.dribbles_attempted,
    agg.dribbles_completed,
    ROUND(agg.dribbles_completed::numeric / NULLIF(agg.dribbles_attempted, 0), 3)  AS dribble_success_rate,
    agg.dispossessed,
    agg.miscontrols,
    agg.fouls_committed,
    agg.fouls_won,
    agg.yellow_cards,
    agg.red_cards
FROM agg
JOIN primary_team pt ON pt.player = agg.player
LEFT JOIN primary_position pp ON pp.player = agg.player;

-- unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
CREATE UNIQUE INDEX idx_player_season_stats_player ON player_season_stats (player);

-- Backfill the players table: player_embeddings' foreign key
-- requires names to already exist here. Bio fields (birth_date,
-- preferred_foot, nationality) are still NULL at this point -
-- filled in by the FIFA16 bio enrichment step.

INSERT INTO players (player)
SELECT DISTINCT player FROM player_match_stats
ON CONFLICT (player) DO NOTHING;

-- player_embeddings: kept separate from season stats, so
-- recomputing embeddings never requires recomputing stats
-- (or vice versa). Vector dimension depends on the embedding
-- model used (1536 below is typical for OpenAI
-- text-embedding-3-small - adjust to match your model choice).

CREATE TABLE IF NOT EXISTS player_embeddings (
    player      TEXT PRIMARY KEY REFERENCES players (player),
    embedding   vector(1536),
    model_name  TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);