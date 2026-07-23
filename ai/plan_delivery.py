"""AI delivery planner: turn a plain-English goal into a validated deploy plan.

Given a goal like "free aws demo" or "production on gcp", pick WHERE to deploy —
cloud + target (free-tier vs paid) + environment — using ONLY the choices declared
in platform.json's `delivery` block. The model proposes; deterministic code
validates against the allowlist and falls back to rules if anything is off.

This is the "AI picks the deploy choices, the static pipeline reads them" design:
the workflow YAML is never AI-generated, so nothing AI-written runs with secrets.

CLI:
    python -m ai.plan_delivery "free aws demo"        -> prints plan JSON
    python -m ai.plan_delivery --github-output "..."  -> also writes key=val to $GITHUB_OUTPUT
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from .llm_client import GeminiClient, ask_json
    from .prompts import render
except ImportError:  # pragma: no cover
    from llm_client import GeminiClient, ask_json
    from prompts import render

ENVIRONMENTS = ("staging", "production")


def load_spec(path: str = "platform.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _delivery(spec: dict) -> dict:
    return spec.get("delivery", {})


def rule_based_plan(goal: str, spec: dict) -> dict:
    """Deterministic planner — works with no model at all."""
    d = _delivery(spec)
    clouds = d.get("clouds", {})
    text = (goal or "").lower()

    # cloud: explicit mention wins, else first declared cloud
    cloud = "gcp" if ("gcp" in text or "google" in text) else "aws"
    if cloud not in clouds:
        cloud = next(iter(clouds), "aws")

    want_free = any(w in text for w in ("free", "cheap", "demo", "cost", "trial"))
    environment = "production" if ("prod" in text) else "staging"

    c = clouds.get(cloud, {})
    free_t = c.get("free_tier_target")
    paid_t = c.get("paid_target") or d.get("default_target")
    if want_free and free_t:
        target, reason = free_t, f"goal implies free; using {cloud} free-tier target"
    else:
        target = paid_t or d.get("default_target")
        reason = f"using {cloud} {'paid' if not want_free else 'default'} target"
    return {"cloud": cloud, "target": target, "environment": environment,
            "reason": reason, "source": "fallback"}


def validate_plan(plan: dict, spec: dict) -> list[str]:
    """Return a list of problems; empty means the plan is allowed."""
    d = _delivery(spec)
    clouds = d.get("clouds", {})
    targets = d.get("targets", {})
    problems = []
    cloud = plan.get("cloud")
    target = plan.get("target")
    env = plan.get("environment")
    if cloud not in clouds:
        problems.append(f"cloud '{cloud}' not in delivery.clouds")
    if target not in targets:
        problems.append(f"target '{target}' not in delivery.targets")
    else:
        # the target must be valid FOR this cloud
        c = clouds.get(cloud, {})
        allowed_for_cloud = {c.get("free_tier_target"), c.get("paid_target")}
        if target not in allowed_for_cloud:
            problems.append(f"target '{target}' not offered for cloud '{cloud}'")
    if env not in ENVIRONMENTS:
        problems.append(f"environment '{env}' not in {ENVIRONMENTS}")
    return problems


def plan(goal: str, spec: dict, client=None) -> dict:
    """Ask the model for a plan; validate; fall back to rules on any problem."""
    fb = rule_based_plan(goal, spec)
    if client is None:
        return fb
    prompt = render("plan_delivery", goal=goal,
                    delivery=json.dumps(_delivery(spec), indent=2))
    proposed = ask_json(client, prompt, fb)
    proposed.setdefault("source", "model")
    if validate_plan(proposed, spec):     # off-allowlist -> never trust it
        return fb
    # carry through only the known keys
    return {
        "cloud": proposed["cloud"],
        "target": proposed["target"],
        "environment": proposed.get("environment", fb["environment"]),
        "reason": proposed.get("reason", ""),
        "source": proposed.get("source", "model"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="AI delivery planner")
    ap.add_argument("goal", nargs="*", help="plain-English goal")
    ap.add_argument("--spec", default="platform.json")
    ap.add_argument("--github-output", action="store_true",
                    help="also append key=value lines to $GITHUB_OUTPUT")
    args = ap.parse_args()
    spec = load_spec(args.spec)
    goal = " ".join(args.goal).strip()

    client = None
    if os.environ.get("GEMINI_API_KEY"):
        try:  # pragma: no cover - needs a key
            client = GeminiClient(model="gemini-2.5-flash")
        except Exception:
            client = None

    result = plan(goal, spec, client=client)
    print(json.dumps(result))

    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            for key in ("cloud", "target", "environment"):
                f.write(f"{key}={result[key]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
