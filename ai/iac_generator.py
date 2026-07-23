"""Generate Terraform from platform.json, and run the deterministic checks that
make LLM-written infra safe (the parts that don't need cloud tools).

The full gauntlet also runs `terraform fmt/validate/plan` and `conftest` in CI
(see .github/workflows/deploy.yml). The checks here — allowlist, contract
outputs, and non-destructive plan — are pure Python and fully unit-tested.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    from .llm_client import GeminiClient, LLMClient
    from .prompts import render
except ImportError:  # pragma: no cover
    from llm_client import GeminiClient, LLMClient
    from prompts import render

REQUIRED_OUTPUTS = ("kubeconfig", "database_url", "app_endpoint")


def load_spec(path: str = "platform.json") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sizing_for(spec: dict, environment: str) -> dict:
    intent = spec["environments"][environment]["intent"]
    return spec["sizing"][intent]


def build_brief(spec: dict, provider: str, environment: str) -> str:
    p = spec["providers"][provider]
    sizing = sizing_for(spec, environment)
    return render(
        "iac_generate",
        allowed_resources=p["allowed_resources"],
        cluster_module=p["cluster"]["module"],
        cluster_version=p["cluster"]["version"],
        size_map=p["size_map"],
        required_outputs=list(REQUIRED_OUTPUTS),
        region=p["region"],
        sizing=sizing,
    )


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences the model sometimes wraps around output.

    Turns ```terraform\\n<hcl>\\n``` (or ```hcl / ```) into raw HCL, so what we
    write to main.tf is valid Terraform, not a markdown block.
    """
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        lines = lines[1:]  # drop the opening ``` / ```terraform / ```hcl line
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # drop the closing fence
        t = "\n".join(lines)
    return t.strip() + "\n"


def generate(spec: dict, provider: str, environment: str,
             client: LLMClient | None = None, out_dir: str | None = None) -> str:
    """Ask the model to assemble Terraform, then WRITE it (nothing is applied here).
    Returns the path to the generated file.
    """
    if client is None:
        # Model is data-driven (platform.json generation.model). flash-lite has a
        # much higher free-tier allowance than flash, so it's the default.
        model = spec.get("generation", {}).get("model", "gemini-3.5-flash-lite")
        client = GeminiClient(model=model)
    tf = strip_code_fences(client.ask(build_brief(spec, provider, environment)))
    out_dir = out_dir or os.path.join("infra", "generated", provider)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "main.tf")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tf)
    return path


# --- deterministic checks (the safety net) -------------------------------- #
_RESOURCE_RE = re.compile(r'resource\s+"([A-Za-z0-9_]+)"')
_MODULE_RE = re.compile(r'module\s+"([A-Za-z0-9_]+)"')
_OUTPUT_RE = re.compile(r'output\s+"([A-Za-z0-9_]+)"')


def check_allowlist(tf_text: str, allowed) -> list[str]:
    """Return resource/module types used but NOT on the allowlist."""
    allowed = set(allowed)
    violations = []
    for rtype in _RESOURCE_RE.findall(tf_text):
        if rtype not in allowed:
            violations.append(f"resource {rtype}")
    for mname in _MODULE_RE.findall(tf_text):
        if f"module.{mname}" not in allowed and mname not in allowed:
            violations.append(f"module {mname}")
    return violations


def check_contract(tf_text: str, required=REQUIRED_OUTPUTS) -> list[str]:
    """Return required contract outputs that are missing."""
    declared = set(_OUTPUT_RE.findall(tf_text))
    return [o for o in required if o not in declared]


def assert_nondestructive(plan_json: dict, protected) -> list[str]:
    """Given `terraform show -json <plan>`, return a list of protected resources
    the plan would destroy or replace. Empty list == safe to auto-apply.
    """
    protected = set(protected)
    issues = []
    for change in plan_json.get("resource_changes", []):
        actions = change.get("change", {}).get("actions", [])
        rtype = change.get("type", "")
        is_destroy = "delete" in actions  # "replace" shows as ["delete","create"]
        if is_destroy and rtype in protected:
            issues.append(f"{change.get('address', rtype)} would be {'/'.join(actions)}")
    return issues


# --- CLI ------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Generative IaC helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--provider", required=True)
    g.add_argument("--env", required=True)
    g.add_argument("--spec", default="platform.json")

    a = sub.add_parser("assert-nondestructive")
    a.add_argument("plan_json")
    a.add_argument("--spec", default="platform.json")

    args = parser.parse_args()
    spec = load_spec(args.spec)

    if args.cmd == "generate":  # pragma: no cover - needs GEMINI_API_KEY
        path = generate(spec, args.provider, args.env)
        tf = open(path, encoding="utf-8").read()
        allowed = spec["providers"][args.provider]["allowed_resources"]
        problems = check_allowlist(tf, allowed) + [f"missing output {m}" for m in check_contract(tf)]
        if problems:
            print("[iac] generation rejected:", problems)
            return 1
        print(f"[iac] wrote {path} (allowlist + contract OK; run fmt/validate/plan/conftest next)")
        return 0

    if args.cmd == "assert-nondestructive":
        with open(args.plan_json, encoding="utf-8") as f:
            plan = json.load(f)
        protected = spec.get("policy", {}).get("protect_from_destroy", [])
        issues = assert_nondestructive(plan, protected)
        if issues:
            print("[iac] BLOCKED — plan would harm protected resources:", issues)
            return 1
        print("[iac] plan is non-destructive to protected resources ✅")
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
