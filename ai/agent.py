"""The deployment agent: observe -> diagnose -> act -> verify.

- reasons with an LLMClient (the model), but only ever emits data;
- acts through an Actuator, and only with actions on the allowlist;
- clamps the model's numbers, gates by autonomy level, retries within a budget,
  then escalates;
- falls back to deterministic rules whenever the model is unavailable, so basic
  self-healing never depends on the model being up.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:  # allow running both as a package (`python -m ai.agent`) and as a script
    from .llm_client import GeminiClient, LLMClient, ScriptedLLMClient, ask_json
    from .guardrails import Guardrails, clamp, is_allowed, needs_human, L1_RECOMMEND, L2_ACT
    from .actions import Actuator, K8sActuator, SimulatedActuator, SimulatedCluster
    from .signals import SignalCollector, SimulatedSignals
    from .prompts import render
    from . import telemetry
except ImportError:  # pragma: no cover
    from llm_client import GeminiClient, LLMClient, ScriptedLLMClient, ask_json
    from guardrails import Guardrails, clamp, is_allowed, needs_human, L1_RECOMMEND, L2_ACT
    from actions import Actuator, K8sActuator, SimulatedActuator, SimulatedCluster
    from signals import SignalCollector, SimulatedSignals
    from prompts import render
    import telemetry


def load_spec(path: str = "platform.json") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_guardrails(spec: dict, autonomy: str | None = None) -> Guardrails:
    """Build the agent's guardrails from platform.json's `agent` block."""
    a = spec.get("agent", {})
    bounds = a.get("replica_bounds", [2, 8])
    return Guardrails(
        autonomy=autonomy or a.get("autonomy_default", L2_ACT),
        replica_bounds=(bounds[0], bounds[1]),
        max_node_increase=a.get("max_node_increase", 2),
        retry_budget=a.get("retry_budget", 3),
    )


def maybe_client(spec: dict) -> LLMClient | None:
    """A live Gemini client if a key is set, else None (rules-only)."""
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:  # pragma: no cover - needs a key
        model = spec.get("generation", {}).get("model", "gemini-3.5-flash-lite")
        return GeminiClient(model=model)
    except Exception:
        return None


def rca_summary(client: LLMClient | None, signals: dict) -> str:
    """A short, human-readable root-cause line for a rollback (case-study idea #3)."""
    fallback = (f"health_ok={signals.get('health_ok')}, "
                f"pod_reason={signals.get('pod_reason')}, "
                f"error_rate_rising={signals.get('error_rate_rising')}")
    if client is None:
        return fallback
    try:  # pragma: no cover - needs a key
        prompt = ("In 2 sentences, give the most likely root cause of an unhealthy "
                  "deployment from these signals, for a human on-call:\n"
                  + json.dumps(signals, indent=2))
        return client.ask(prompt).strip() or fallback
    except Exception:
        return fallback


def canary_check(observe, actuator: Actuator, client: LLMClient | None = None,
                 record=telemetry.record_decision) -> bool:
    """Post-deploy gate: healthy -> keep; unhealthy -> roll back with an RCA.
    Returns True if the canary was kept, False if it was rolled back.
    """
    signals = observe()
    if signals.get("health_ok"):
        record(signals, {"action": "hold", "diagnosis": "canary healthy", "source": "agent"},
               "allowed", {"verified": True})
        print("[agent] canary healthy -> keep")
        return True
    reason = rca_summary(client, signals)
    print(f"[agent] canary UNHEALTHY -> rollback\n[agent] RCA: {reason}")
    try:
        actuator.execute("rollback", {})
    except Exception as e:  # noqa: BLE001 - e.g. no prior revision on a first deploy
        print(f"[agent] rollback could not run ({e}); likely the first release "
              f"(nothing to revert to). Leaving it for a human.")
    record(signals, {"action": "rollback", "diagnosis": reason, "source": "agent"},
           "allowed", {"verified": False})
    return False


def rule_based(signals: dict) -> dict:
    """Boring, reliable fallback. Works with no model at all."""
    reason = signals.get("pod_reason")
    if reason == "ImagePullBackOff":
        return {"action": "redeploy", "params": {}, "diagnosis": "image pull failing", "source": "fallback"}
    if reason == "Pending":
        return {"action": "scale_nodes", "params": {"delta": 1}, "diagnosis": "pods unschedulable", "source": "fallback"}
    if reason == "CrashLoopBackOff":
        return {"action": "rollback", "params": {}, "diagnosis": "new version crash-looping", "source": "fallback"}
    if signals.get("network_analysis"):
        return {"action": "restart_workload", "params": {"workload": "backend"},
                "diagnosis": f"analysis: {signals['network_analysis']}", "source": "fallback"}
    if signals.get("error_rate_rising"):
        return {"action": "run_network_analysis", "params": {}, "diagnosis": "error rate rising", "source": "fallback"}
    return {"action": "hold", "params": {}, "diagnosis": "nothing actionable", "source": "fallback"}


def decide(client: LLMClient | None, g: Guardrails, signals: dict) -> dict:
    """Ask the model to pick an allowlisted action; fall back to rules on any
    problem or if the model returns something off the allowlist.
    """
    fb = rule_based(signals)
    if client is None:
        return fb
    prompt = render(
        "agent_decide",
        allowed=sorted(g.allowed),
        signals=json.dumps(signals, indent=2),
    )
    decision = ask_json(client, prompt, fb)
    decision.setdefault("source", "model")
    if not is_allowed(decision.get("action", ""), g):
        # never trust the model blindly
        return fb
    return decision


def run_loop(observe, actuator: Actuator, g: Guardrails, client=None,
             verify=None, on_escalate=None, record=telemetry.record_decision) -> bool:
    """Returns True if the system ended healthy, False if it escalated/gave up."""
    if verify is None:
        verify = lambda: observe().get("health_ok", False)

    for _ in range(g.retry_budget):
        signals = observe()                                   # OBSERVE
        decision = clamp(decide(client, g, signals), g)       # DIAGNOSE (+clamp)

        if decision["action"] == "hold":
            record(signals, decision, "allowed", {"verified": True})
            return True

        if needs_human(decision, g):                          # L0/L1 or gated
            record(signals, decision, "needs-approval", {"verified": False})
            if on_escalate:
                on_escalate(decision)
            return False

        actuator.execute(decision["action"], decision["params"])  # ACT
        ok = verify()                                             # VERIFY
        record(signals, decision, "allowed", {"verified": ok})
        if ok:
            return True

    escalation = {"action": "escalate", "diagnosis": "fix did not hold within budget", "source": "agent"}
    record(observe(), escalation, "escalated", {"verified": False})
    if on_escalate:
        on_escalate(escalation)
    return False


# --------------------------------------------------------------------------- #
# Demo: run the loop against a simulated cluster, no external dependencies.
# --------------------------------------------------------------------------- #
def _demo() -> None:
    print("\n=== Scenario 1: new release crash-loops (L2, auto-remediate) ===")
    cluster = SimulatedCluster(pod_reason="CrashLoopBackOff", healthy=False)
    actuator = SimulatedActuator(cluster)
    signals = SimulatedSignals(cluster)
    ok = run_loop(signals.snapshot, actuator, Guardrails(autonomy=L2_ACT))
    print(f"-> resolved={ok}; actions taken={[a for a, _ in actuator.history]}")
    assert ok and ("rollback" in [a for a, _ in actuator.history])

    print("\n=== Scenario 2: error rate rising -> network analysis -> restart ===")
    cluster = SimulatedCluster(error_rate_rising=True, healthy=False)
    actuator = SimulatedActuator(cluster)
    signals = SimulatedSignals(cluster)
    ok = run_loop(signals.snapshot, actuator, Guardrails(autonomy=L2_ACT))
    print(f"-> resolved={ok}; actions taken={[a for a, _ in actuator.history]}")
    assert ok and actuator.history[0][0] == "run_network_analysis"

    print("\n=== Scenario 3: same fault, but L1 (recommend) -> escalates, no action ===")
    cluster = SimulatedCluster(pod_reason="CrashLoopBackOff", healthy=False)
    actuator = SimulatedActuator(cluster)
    signals = SimulatedSignals(cluster)
    escalated = {}
    ok = run_loop(signals.snapshot, actuator, Guardrails(autonomy=L1_RECOMMEND),
                  on_escalate=lambda d: escalated.update(d))
    print(f"-> resolved={ok}; actions taken={actuator.history}; escalated={escalated.get('action')}")
    assert not ok and actuator.history == []

    print("\nAll demo scenarios behaved as expected. ✅")


def main() -> None:
    parser = argparse.ArgumentParser(description="Idea Board deployment agent")
    parser.add_argument("mode", nargs="?", default="demo", choices=["demo", "canary", "watch"])
    parser.add_argument("--endpoint", default="http://frontend")
    parser.add_argument("--namespace", default="idea")
    args = parser.parse_args()

    if args.mode == "demo":
        _demo()
        return

    # --- live modes: real signals + real actuator against the cluster ---
    spec = load_spec()
    collector = SignalCollector(args.endpoint, namespace=args.namespace)
    actuator = K8sActuator(namespace=args.namespace)
    client = maybe_client(spec)

    if args.mode == "canary":  # pragma: no cover - requires a live cluster
        # Verify the just-shipped release; roll back with an RCA if it's unhealthy.
        kept = canary_check(collector.snapshot, actuator, client)
        sys.exit(0 if kept else 1)

    if args.mode == "watch":  # pragma: no cover - requires a live cluster
        # One self-heal pass (the CronJob invokes this every minute).
        g = build_guardrails(spec, os.environ.get("AGENT_AUTONOMY"))
        ok = run_loop(collector.snapshot, actuator, g, client=client)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
