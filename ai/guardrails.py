"""The cage the agent cannot open.

The allowlist contains ONLY reversible actions. Irreversible operations
(deleting data, destroying infrastructure) are deliberately absent, so the model
cannot even express them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Autonomy levels
L0_OBSERVE = "L0"     # analyse only, take no action
L1_RECOMMEND = "L1"   # propose an action, wait for a human
L2_ACT = "L2"         # execute reversible, allowlisted actions

ALLOWLIST = {
    "hold",                   # do nothing, keep watching
    "escalate",               # stop and page a human, with the reason
    "run_network_analysis",   # read-only diagnostics (no changes)
    "redeploy",               # re-apply the current release
    "restart_workload",       # rolling restart of one service
    "scale_replicas",         # change number of app copies (within bounds)
    "scale_nodes",            # add machines (capped)
    "promote_canary",         # send all traffic to the new version
    "abort_canary",           # drop the new version, keep the old
    "rollback",               # go back to the previous good version
}

# Never selectable by the model. Present only so reviewers can see the intent.
FORBIDDEN = {"delete_database", "destroy_infra", "delete_stateful"}


@dataclass
class Guardrails:
    autonomy: str = L2_ACT
    allowed: set = field(default_factory=lambda: set(ALLOWLIST))
    namespace: str = "idea"
    replica_bounds: tuple = (2, 8)
    max_node_increase: int = 2
    retry_budget: int = 3
    require_approval: set = field(default_factory=set)


def is_allowed(action: str, g: Guardrails) -> bool:
    """An action must be on the global allowlist AND enabled for this environment.
    Forbidden actions are rejected even if someone mistakenly adds them.
    """
    if action in FORBIDDEN:
        return False
    return action in ALLOWLIST and action in g.allowed


def clamp(decision: dict, g: Guardrails) -> dict:
    """Force any numbers the model proposed into safe bounds before execution."""
    action = decision.get("action")
    params = dict(decision.get("params") or {})
    if action == "scale_replicas":
        lo, hi = g.replica_bounds
        try:
            want = int(params.get("replicas", lo))
        except (TypeError, ValueError):
            want = lo
        params["replicas"] = max(lo, min(hi, want))
    if action == "scale_nodes":
        try:
            want = int(params.get("delta", 1))
        except (TypeError, ValueError):
            want = 1
        params["delta"] = max(1, min(g.max_node_increase, want))
    decision["params"] = params
    return decision


def needs_human(decision: dict, g: Guardrails) -> bool:
    """True when the agent must hand off instead of acting on its own."""
    action = decision.get("action")
    if action == "escalate":
        return True
    if g.autonomy != L2_ACT:  # L0/L1 never act autonomously
        return True
    if action in g.require_approval:
        return True
    return False
