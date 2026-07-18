"""
scout_agent.py

Core logic for the natural-language scouting agent: schema description,
tool definitions, SQL execution, player-similarity search, and the Claude
tool-use loop. Used by both agent.py (CLI) and app.py (FastAPI service).
"""

import json
import os
import re

import anthropic
from sqlalchemy import create_engine, text

MODEL = "claude-sonnet-5"
MAX_ROWS = 50

# Read-only role - see create_readonly_role.sql. Even if Claude writes a
# bad query, this connection physically cannot modify data.
# DATABASE_URL env var overrides this - set to something like
# postgresql://agent_readonly:agent_readonly_password@db:5432/ai_scout
# when running inside Docker Compose (service name "db", not "localhost").
DEFAULT_DB_URL = "postgresql://agent_readonly:agent_readonly_password@localhost:5432/ai_scout"

SCHEMA_DESCRIPTION = """
You have access to a Postgres database about the Premier League 2015/2016
season (StatsBomb event data, aggregated to player-season level). It is a
single historical season, not current data.

Table: players
  player          TEXT PRIMARY KEY  - player's full name
  birth_date      DATE              - use this to compute age; NULL for ~20% of players
  preferred_foot  TEXT              - 'Left' or 'Right'; NULL if unknown
  nationality     TEXT              - NULL if unknown

  IMPORTANT: to compute a player's age AS OF the 2015/16 season (not
  today), use: EXTRACT(YEAR FROM AGE('2015-08-08', birth_date))

View: player_season_stats
  player, team, position               - identity (position = most-played position this season; NULL if unknown)
  appearances, total_minutes           - playing time
  passes_attempted, passes_completed, pass_accuracy
  key_passes, key_passes_per90
  crosses_attempted, crosses_completed
  shots, shots_on_target, xg_total, xg_per90, goals, goals_per90
  pressures, pressures_per90, ball_recoveries, interceptions, interceptions_per90
  ground_duels_won, ground_duels_total, ground_duel_win_rate
  dribbles_attempted, dribbles_completed, dribble_success_rate
  dispossessed, miscontrols, fouls_committed, fouls_won, yellow_cards, red_cards

  NOTE: progressive_passes, progressive_carries, touches_in_box,
  aerial_duels_won, and aerial_duels_total are always 0 - not yet
  implemented. Do not use them, and mention to the user if a question
  specifically needs them that this data isn't available yet.

To join bio data with stats: player_season_stats.player = players.player

For "players similar to X" / "playing style like X" questions, use the
find_similar_players tool instead of writing SQL yourself. It compares
z-score-normalized per-90 statistical profiles (cosine similarity) for
players with > 450 minutes. Similarity is about statistical style, not
reputation or transfer value - say so if relevant.

Guidelines:
- Only write SELECT queries.
- Always add a reasonable minutes_played/appearances floor (e.g.
  total_minutes > 450) for "best at X" style questions, so a player with
  10 minutes and 1 lucky shot doesn't top the list. Mention this filter
  in your answer.
- If bio data (age/foot/nationality) is NULL for a relevant player,
  say so rather than omitting them silently.
"""

TOOLS = [
    {
        "name": "run_sql_query",
        "description": "Run a read-only SQL SELECT query against the Premier League 2015/16 database and return the results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A SQL SELECT query.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_similar_players",
        "description": (
            "Find players whose statistical profile (per-90 metrics, z-score "
            "normalized, cosine similarity) is most similar to a given player "
            "in the Premier League 2015/16 season. Use for 'similar to X' / "
            "'plays like X' questions. Only covers players with > 450 minutes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {
                    "type": "string",
                    "description": "Player name (partial names OK, e.g. 'Kante' or 'Vardy').",
                },
                "top_n": {
                    "type": "integer",
                    "description": "How many similar players to return (default 10).",
                },
            },
            "required": ["player_name"],
        },
    },
]


def get_engine():
    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    return create_engine(db_url)


def run_sql_query(engine, query: str) -> str:
    stripped = query.strip().rstrip(";")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        return json.dumps({"error": "Only SELECT queries are allowed."})

    if "limit" not in stripped.lower():
        stripped += f" LIMIT {MAX_ROWS}"

    try:
        with engine.connect() as conn:
            conn.execute(text("SET statement_timeout = 5000"))  # 5s safety timeout
            result = conn.execute(text(stripped))
            rows = [dict(row._mapping) for row in result]
        return json.dumps(rows, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def find_similar_players(engine, player_name: str, top_n: int = 10) -> str:
    top_n = max(1, min(int(top_n or 10), 25))
    try:
        with engine.connect() as conn:
            # Resolve the (possibly partial) name against players that have
            # an embedding. Unaccent isn't installed, so match loosely.
            match = conn.execute(
                text("""
                    SELECT player FROM player_embeddings
                    WHERE player ILIKE :pat
                    ORDER BY length(player) ASC
                    LIMIT 5
                """),
                {"pat": f"%{player_name}%"},
            ).fetchall()

            if not match:
                return json.dumps({
                    "error": f"No embedded player matched '{player_name}'. "
                             "They may have played under 450 minutes, or the "
                             "name is spelled differently in StatsBomb data."
                })
            if len(match) > 1:
                names = [m.player for m in match]
                return json.dumps({
                    "ambiguous": True,
                    "candidates": names,
                    "note": "Multiple players matched - re-call with a more specific name.",
                })

            resolved = match[0].player
            rows = conn.execute(
                text("""
                    SELECT e2.player, ps.team, ps.position, ps.total_minutes,
                           ROUND((1 - (e1.embedding <=> e2.embedding))::numeric, 3) AS similarity
                    FROM player_embeddings e1
                    JOIN player_embeddings e2 ON e2.player != e1.player
                    JOIN player_season_stats ps ON ps.player = e2.player
                    WHERE e1.player = :name
                    ORDER BY e1.embedding <=> e2.embedding
                    LIMIT :n
                """),
                {"name": resolved, "n": top_n},
            ).fetchall()

        return json.dumps({
            "query_player": resolved,
            "similar": [dict(r._mapping) for r in rows],
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def ask(client, engine, question: str, return_queries: bool = False):
    messages = [{"role": "user", "content": question}]
    executed_queries = []

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SCHEMA_DESCRIPTION,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            answer = "".join(block.text for block in response.content if block.type == "text")
            if return_queries:
                return answer, executed_queries
            return answer

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "run_sql_query":
                query = block.input["query"]
                executed_queries.append(query)
                result = run_sql_query(engine, query)
            elif block.name == "find_similar_players":
                name = block.input["player_name"]
                top_n = block.input.get("top_n", 10)
                executed_queries.append(f"[similarity] {name} (top {top_n})")
                result = find_similar_players(engine, name, top_n)
            else:
                result = json.dumps({"error": f"Unknown tool: {block.name}"})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})