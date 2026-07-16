"""
app.py

FastAPI service for the scouting agent.

Endpoints:
    GET  /health        - basic health check
    POST /ask           - {"question": "..."} -> {"answer": "...", "sql_queries": [...]}

Run locally:
    uvicorn app:app --reload

Run via Docker: see Dockerfile / docker-compose.yml
"""

import anthropic
from fastapi import FastAPI
from pydantic import BaseModel

from scout_agent import ask, get_engine

app = FastAPI(title="AI Football Scout Assistant")

_client = anthropic.Anthropic()
_engine = get_engine()


class Question(BaseModel):
    question: str


class Answer(BaseModel):
    answer: str
    sql_queries: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask", response_model=Answer)
def ask_endpoint(payload: Question):
    answer, queries = ask(_client, _engine, payload.question, return_queries=True)
    return Answer(answer=answer, sql_queries=queries)
