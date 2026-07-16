CREATE EXTENSION IF NOT EXISTS vector;      -- for player similarity/embedding search
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- for UUID generation


-- 1) events: raw event table (wide but shallow)
--    common fields as columns, type-specific fields in JSONB

CREATE TABLE events (
    event_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    match_id        BIGINT NOT NULL,
    event_index     INT NOT NULL,
    period          SMALLINT,
    minute          SMALLINT,
    second          SMALLINT,
    team            TEXT,
    player          TEXT,
    position        TEXT,
    location_x      REAL,
    location_y      REAL,
    type            TEXT NOT NULL,
    possession      INT,
    possession_team TEXT,
    play_pattern    TEXT,
    duration        REAL,
    under_pressure  BOOLEAN DEFAULT FALSE,
    extra           JSONB,        -- type-specific fields (pass_recipient, shot_xg, carry_end_location, etc.)
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_events_match_id ON events (match_id);
CREATE INDEX idx_events_type     ON events (type);
CREATE INDEX idx_events_player   ON events (player);
CREATE INDEX idx_events_extra    ON events USING GIN (extra);

-- 2) player_match_stats: aggregated table the agent will query

CREATE TABLE player_match_stats (
    id                    SERIAL PRIMARY KEY,
    player                TEXT NOT NULL,
    match_id              BIGINT NOT NULL,
    team                  TEXT,
    position              TEXT,     -- position played in this match (matters for interpretation)
    minutes_played        REAL,
    passes_attempted      INT DEFAULT 0,
    passes_completed      INT DEFAULT 0,
    pass_accuracy         REAL,
    progressive_passes    INT DEFAULT 0,
    key_passes            INT DEFAULT 0,
    crosses_attempted     INT DEFAULT 0,
    crosses_completed     INT DEFAULT 0,
    shots                 INT DEFAULT 0,
    shots_on_target       INT DEFAULT 0,
    xg_total              REAL DEFAULT 0,
    goals                 INT DEFAULT 0,
    touches_in_box        INT DEFAULT 0,
    progressive_carries   INT DEFAULT 0,
    pressures             INT DEFAULT 0,
    ball_recoveries       INT DEFAULT 0,
    interceptions         INT DEFAULT 0,
    ground_duels_won      INT DEFAULT 0,
    ground_duels_total    INT DEFAULT 0,
    aerial_duels_won      INT DEFAULT 0,
    aerial_duels_total    INT DEFAULT 0,
    dribbles_attempted    INT DEFAULT 0,
    dribbles_completed    INT DEFAULT 0,
    dispossessed          INT DEFAULT 0,
    miscontrols           INT DEFAULT 0,
    fouls_committed       INT DEFAULT 0,
    fouls_won             INT DEFAULT 0,
    yellow_cards          INT DEFAULT 0,
    red_cards             INT DEFAULT 0,
    created_at            TIMESTAMPTZ DEFAULT now(),
    UNIQUE (player, match_id)
);

CREATE INDEX idx_pms_player   ON player_match_stats (player);
CREATE INDEX idx_pms_match_id ON player_match_stats (match_id);


-- 3) players: bio data placeholder (filled from FIFA16/FBref -
--    age, foot, nationality - fields StatsBomb doesn't provide)

CREATE TABLE players (
    player          TEXT PRIMARY KEY,
    birth_date      DATE,
    preferred_foot  TEXT,
    nationality     TEXT,
    source          TEXT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);
