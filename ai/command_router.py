"""AI-assisted PREVIEW command generation from a plain-English PR comment.

A reviewer types e.g. `/ops give me a preview` or `/ops tear it down` on a PR.
An LLM maps that intent to EXACTLY ONE command on a small allowlist — and every
command is scoped to an ISOLATED preview release/namespace (`idea-pr-<number>`).

Production safety is structural: the allowlist contains NO production action
(no prod deploy, rollback, or scale), and every generated command targets the
PR-scoped namespace only — it can never touch the production release (`idea`).

CLI (used by .github/workflows/pr-command.yml):
    PR_NUMBER=42 python -m ai.command_router "spin up a preview"
"""
from __future__ import annotations

import os
import sys

try:
    from .llm_client import GeminiClient, ask_json
    from .prompts import render
except ImportError:  # pragma: no cover
    from llm_client import GeminiClient, ask_json
    from prompts import render

# The ONLY commands the model may choose — all PREVIEW/DEV, all reversible.
# Nothing here can affect production.
ALLOWED_COMMANDS = {
    "deploy-preview": "Deploy an isolated preview of THIS PR (dev only) and return its link",
    "preview-status": "Show this PR's preview status",
    "preview-down": "Tear down this PR's preview",
    "help": "List the available commands",
}


def rule_based_route(text: str) -> dict:
    """Deterministic fallback — works with no model."""
    t = (text or "").lower()
    if any(w in t for w in ("down", "tear", "destroy", "remove", "delete", "stop", "clean")):
        return {"command": "preview-down", "reason": "teardown requested", "source": "fallback"}
    if any(w in t for w in ("status", "health", "state", "how is", "what's")):
        return {"command": "preview-status", "reason": "status requested", "source": "fallback"}
    if any(w in t for w in ("preview", "deploy", "link", "url", "see it", "spin", "demo", "try")):
        return {"command": "deploy-preview", "reason": "preview requested", "source": "fallback"}
    return {"command": "help", "reason": "unrecognised request", "source": "fallback"}


def route(text: str, client=None) -> dict:
    """Ask the model to pick an allowlisted command; fall back / reject off-list."""
    fb = rule_based_route(text)
    if client is None:
        return fb
    menu = "\n".join(f"- {k}: {v}" for k, v in ALLOWED_COMMANDS.items())
    decision = ask_json(client, render("command_router", text=text, commands=menu), fb)
    if decision.get("command") not in ALLOWED_COMMANDS:
        return fb
    decision.setdefault("source", "model")
    return decision


def preview_release(pr: str | int) -> str:
    """Isolated release/namespace name for a PR — never the production 'idea'."""
    return f"idea-pr-{pr}"


def generate_commands(decision: dict, pr: str | int = "0") -> list[str]:
    """Concrete, preview-scoped shell steps. Generated deterministically (not by
    the LLM), and always targeting the PR-scoped namespace — so production is safe.
    """
    cmd = decision["command"]
    rel = preview_release(pr)  # e.g. idea-pr-42 (release AND namespace)
    if cmd == "deploy-preview":
        return [
            f"helm upgrade --install {rel} deploy/helm -n {rel} --create-namespace \\",
            f"  --set image.backend=$REG/backend:$SHA \\",
            f"  --set image.frontend=$REG/frontend:$SHA \\",
            f"  --set service.frontendType=LoadBalancer --wait",
        ]
    if cmd == "preview-status":
        return [f"kubectl get pods -n {rel}", f"helm status {rel} -n {rel}"]
    if cmd == "preview-down":
        return [f"helm uninstall {rel} -n {rel}", f"kubectl delete namespace {rel}"]
    return ["# available: " + ", ".join(ALLOWED_COMMANDS)]


def as_markdown(text: str, decision: dict, pr: str | int = "0") -> str:
    cmds = "\n".join(generate_commands(decision, pr))
    src = "📏 rules (model unavailable)" if decision.get("source") == "fallback" else "🤖 model"
    return (
        f"### 🛠️ Preview command interpreted\n"
        f"**You said:** `{text}`\n\n"
        f"**Interpreted as:** `{decision['command']}` — {decision.get('reason', '')}  \n"
        f"**Scope:** preview `idea-pr-{pr}` only  ·  **Source:** {src}\n\n"
        f"**Generated commands:**\n```bash\n{cmds}\n```\n"
        f"_🔒 Production-safe: `/ops` can only act on this PR's isolated preview "
        f"(`idea-pr-{pr}`). It cannot deploy to, roll back, or scale production._"
    )


def main() -> int:
    text = " ".join(sys.argv[1:]).strip()
    pr = os.environ.get("PR_NUMBER", "0")
    client = None
    if os.environ.get("GEMINI_API_KEY"):
        try:  # pragma: no cover - needs a key
            from . import iac_generator
            model = iac_generator.load_spec().get("generation", {}).get("model", "gemini-3.5-flash-lite")
            client = GeminiClient(model=model)
        except Exception:
            client = None
    decision = route(text, client)
    # Emit the chosen command on its own line so the workflow can act on it.
    print(f"COMMAND={decision['command']}")
    print(as_markdown(text, decision, pr))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
