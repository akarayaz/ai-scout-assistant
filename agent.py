"""
agent.py

CLI entry point for the scouting agent - thin wrapper around
scout_agent.py's shared logic (also used by app.py, the FastAPI service).

Usage:
    python agent.py
    (then type questions interactively, Ctrl+C to quit)

Setup:
    pip install anthropic sqlalchemy psycopg2-binary
    export ANTHROPIC_API_KEY=your-key-here
"""

import anthropic

from scout_agent import ask, get_engine


def main():
    client = anthropic.Anthropic()
    engine = get_engine()

    print("Scouting assistant ready. Ask a question (Ctrl+C to quit).\n")
    while True:
        try:
            question = input("> ")
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break
        if not question.strip():
            continue
        answer, queries = ask(client, engine, question, return_queries=True)
        for q in queries:
            print(f"  [SQL] {q}")
        print(f"\n{answer}\n")


if __name__ == "__main__":
    main()