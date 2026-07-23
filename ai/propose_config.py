"""Turn a plain-English goal into concrete sizing numbers."""
import json
import sys

try:
    from .llm_client import GeminiClient, ask_json
    from .prompts import render
except ImportError:
    from llm_client import GeminiClient, ask_json
    from prompts import render


def main(goal: str):
    prompt = render("propose_config", goal=goal)
    fallback = {"node_count": 2, "node_size": "small", "db_size": "small",
                "replica_count": 2, "reason": "AI unavailable; safe defaults."}
    try:
        client = GeminiClient(model="gemini-2.5-flash")
    except Exception:
        print(json.dumps(fallback))
        return
    print(json.dumps(ask_json(client, prompt, fallback)))


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "cost-sensitive staging")
