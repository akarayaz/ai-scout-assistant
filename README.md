# AI Football Scout Assistant

Event-level football data pipeline with a natural-language scouting agent,
built on StatsBomb's open data for the Premier League 2015/2016 season.

## Overview

Raw StatsBomb match events are ingested into Postgres, aggregated into
per-match and per-season player statistics (passing, shooting, pressing,
duels, per-90 metrics), and enriched with player bio data (birth date,
nationality, preferred foot). A Claude-powered agent answers natural-language
scouting questions ("who are the best young left-footed pressing
midfielders?") by writing and running SQL against this data, served through
a FastAPI service with a Streamlit frontend.

## Architecture

```
StatsBomb open data (events)
        |
   ingestion.py
        |
        v
   Postgres (events, player_match_stats)
        |
   player_season_view.sql
        |
        v
   player_season_stats (materialized view, per-90 metrics)
        |
   fifa_bio_ingestion.py + fifa_bio_manual_overrides.py
        |
        v
   players (birth_date, nationality, preferred_foot)
        |
   build_player_embeddings.py
        |
        v
   player_embeddings (19-dim stat vectors, pgvector)
        |
   scout_agent.py (Claude tool-use loop: read-only SQL + similarity search)
        |
        v
   app.py (FastAPI) <-- agent.py (CLI, for local testing)
        |
        v
   streamlit_app.py (frontend)
```

- **Storage:** Postgres with the `pgvector` extension, run via Docker Compose
- **Player similarity:** 19-dimensional statistical "style" vectors (per-90
  volumes and rates, z-score normalized) compared via pgvector cosine
  similarity - exposed to the agent as a `find_similar_players` tool
- **Event data:** [StatsBomb Open Data](https://github.com/statsbomb/open-data),
  Premier League 2015/2016 (380 matches, ~1.3M events)
- **Bio data:** FIFA 16 player ratings (birth date, nationality, preferred
  foot), matched against StatsBomb player names
- **Agent:** Claude (Anthropic API) with a `run_sql_query` tool, restricted
  to a read-only Postgres role so generated SQL can never modify data
- **API:** FastAPI service (`/ask`), containerized alongside Postgres

## Setup

1. Start Postgres (applies `schema.sql` automatically on first run):
   ```
   docker compose up -d
   ```

2. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run the event ingestion pipeline (pulls all 380 matches, takes a while):
   ```
   python ingestion.py
   ```

4. Create the player-season aggregation view:
   ```
   cat player_season_view.sql | docker exec -i ai_scout_db psql -U scout -d ai_scout
   ```

5. Bio enrichment - download `players_16.csv` from the
   [FIFA complete player dataset](https://www.kaggle.com/datasets/stefanoleone992/fifa-21-complete-player-dataset)
   on Kaggle, place it in the repo root, then:
   ```
   python fifa_bio_ingestion.py
   python fifa_bio_manual_overrides.py
   ```

6. Create the read-only role the agent uses:
   ```
   cat create_readonly_role.sql | docker exec -i ai_scout_db psql -U scout -d ai_scout
   ```

7. Build the player similarity embeddings (statistical style vectors,
   see `build_player_embeddings.py`):
   ```
   python build_player_embeddings.py
   ```

8. Set up your Anthropic API key:
   ```
   cp .env.example .env
   # edit .env and add your ANTHROPIC_API_KEY
   ```

9. Run the agent - either the CLI, for local testing:
   ```
   python agent.py
   ```
   or the full API service via Docker:
   ```
   docker compose up -d --build
   curl -X POST http://localhost:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "Who scored the most goals per 90 minutes?"}'
   ```

10. Run the Streamlit frontend (talks to the FastAPI service over HTTP):
   ```
   streamlit run streamlit_app.py
   ```
   Opens at `http://localhost:8501`.

`explore.ipynb` contains the initial data exploration used to pick the
competition/season and inspect the event schema.

## Data sources

- **StatsBomb Open Data** - used under StatsBomb's open data license terms.
  See the [source repository](https://github.com/statsbomb/open-data) for
  full licensing details.
- **FIFA player ratings** via the
  [FIFA complete player dataset](https://www.kaggle.com/datasets/stefanoleone992/fifa-21-complete-player-dataset)
  on Kaggle. Not included in this repo (see `.gitignore`) - download
  separately per the setup steps above.

## Status

- [x] Event ingestion pipeline (StatsBomb -> Postgres)
- [x] Player-season aggregation (materialized view, per-90 metrics)
- [x] Bio enrichment (83% player coverage: birth date, nationality,
      preferred foot)
- [x] Natural-language query agent (Claude tool-use API)
- [x] API + deployment (FastAPI + Docker)
- [x] Player similarity search (19-dim z-scored per-90 stat vectors,
      pgvector cosine similarity, exposed as an agent tool)
- [x] Simple frontend (Streamlit)
- [ ] Broader agent testing / eval set
- [ ] Multi-tenancy / auth (out of scope for now)

Some fields (`progressive_passes`, `progressive_carries`, `touches_in_box`,
`aerial_duels_won/total`) are defined in the schema but not yet populated -
they require attacking-direction normalization or event-linking logic not
yet implemented. See comments in `ingestion.py` for details.

## Tech stack

Python, Postgres, pgvector, Docker, FastAPI, Claude API (Anthropic),
pandas, SQLAlchemy, statsbombpy
