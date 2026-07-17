"""
streamlit_app.py

Simple frontend for the scouting agent. Talks to the FastAPI service
over HTTP (does not touch the DB/LLM directly) - keeps the frontend
thin and the API as the single source of truth.

Usage:
    streamlit run streamlit_app.py

Requires the API to be running (see README - docker compose up -d --build,
or `uvicorn app:app` locally).
"""

import os

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

EXAMPLE_QUESTIONS = [
    "Who scored the most goals per 90 minutes?",
    "Which young left-footed midfielders had good pressing numbers?",
    "Compare Jamie Vardy and Harry Kane's goal-scoring per 90 minutes",
]

st.set_page_config(page_title="AI Football Scout Assistant", page_icon="⚽")
st.title("⚽ AI Football Scout Assistant")
st.caption("Premier League 2015/2016 · StatsBomb event data · Claude-powered")

if "history" not in st.session_state:
    st.session_state.history = []

st.write("Try an example:")
cols = st.columns(len(EXAMPLE_QUESTIONS))
example_clicked = None
for col, q in zip(cols, EXAMPLE_QUESTIONS):
    if col.button(q, use_container_width=True):
        example_clicked = q

question = st.chat_input("Ask a scouting question...")
if example_clicked:
    question = example_clicked

for entry in st.session_state.history:
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        st.write(entry["answer"])
        if entry["sql_queries"]:
            with st.expander("SQL used"):
                for q in entry["sql_queries"]:
                    st.code(q, language="sql")

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Querying the database..."):
            try:
                resp = requests.post(f"{API_URL}/ask", json={"question": question}, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                answer = data["answer"]
                sql_queries = data.get("sql_queries", [])
            except requests.exceptions.RequestException as e:
                answer = f"Couldn't reach the API ({API_URL}). Is it running? Error: {e}"
                sql_queries = []

        st.write(answer)
        if sql_queries:
            with st.expander("SQL used"):
                for q in sql_queries:
                    st.code(q, language="sql")

    st.session_state.history.append({
        "question": question,
        "answer": answer,
        "sql_queries": sql_queries,
    })
