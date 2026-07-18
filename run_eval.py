"""
run_eval.py

Runs the eval set against the scouting agent and reports an accuracy
score. Checks are deterministic string matches (case-insensitive):

  must_contain_all - every string must appear in the answer
  must_contain_any - at least one string must appear
  must_not_contain - none of the strings may appear

Calls the agent logic directly (no HTTP) - requires ANTHROPIC_API_KEY
and the database running on localhost, same as agent.py.

Usage:
    python run_eval.py

Writes detailed results to eval_results.json.
"""

import json
import time

import anthropic

from scout_agent import ask, get_engine

EVAL_SET_PATH = "eval_set.json"
RESULTS_PATH = "eval_results.json"


def check(answer: str, case: dict) -> tuple[bool, list[str]]:
    a = answer.lower()
    failures = []

    for s in case.get("must_contain_all", []):
        if s.lower() not in a:
            failures.append(f"missing required: '{s}'")

    any_list = case.get("must_contain_any", [])
    if any_list and not any(s.lower() in a for s in any_list):
        failures.append(f"none of the expected strings found: {any_list}")

    for s in case.get("must_not_contain", []):
        if s.lower() in a:
            failures.append(f"contains forbidden: '{s}'")

    return (len(failures) == 0), failures


def main():
    with open(EVAL_SET_PATH) as f:
        cases = json.load(f)

    client = anthropic.Anthropic()
    engine = get_engine()

    results = []
    passed = 0

    print(f"Running {len(cases)} eval cases...\n")
    for case in cases:
        start = time.time()
        try:
            answer, queries = ask(client, engine, case["question"], return_queries=True)
            error = None
        except Exception as e:
            answer, queries, error = "", [], str(e)

        elapsed = round(time.time() - start, 1)

        if error:
            ok, failures = False, [f"exception: {error}"]
        else:
            ok, failures = check(answer, case)

        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']} ({case['category']}, {elapsed}s)")
        for fmsg in failures:
            print(f"       {fmsg}")

        results.append({
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "passed": ok,
            "failures": failures,
            "answer": answer,
            "queries": queries,
            "seconds": elapsed,
        })

    total = len(cases)
    score = round(100 * passed / total, 1)
    print(f"\nScore: {passed}/{total} ({score}%)")

    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["passed"])
    for cat, vals in sorted(by_cat.items()):
        print(f"  {cat:12s} {sum(vals)}/{len(vals)}")

    with open(RESULTS_PATH, "w") as f:
        json.dump({"score": score, "passed": passed, "total": total, "results": results}, f, indent=2)
    print(f"\nDetailed results written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
