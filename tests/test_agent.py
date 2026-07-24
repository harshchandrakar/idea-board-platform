import json
import os

import pytest

from ai.agent import (
    decide, rule_based, run_loop, build_guardrails, canary_check, rca_summary,
)
from ai.actions import SimulatedActuator, SimulatedCluster
from ai.signals import SimulatedSignals
from ai.guardrails import Guardrails, L1_RECOMMEND, L2_ACT
from ai.llm_client import ScriptedLLMClient


def _silent(*args, **kwargs):
    return None  # swallow telemetry output in tests


ROOT = os.path.dirname(os.path.dirname(__file__))


def test_build_guardrails_from_spec():
    import json as _json
    spec = _json.load(open(os.path.join(ROOT, "platform.json")))
    g = build_guardrails(spec)
    assert g.retry_budget == spec["agent"]["retry_budget"]
    assert list(g.replica_bounds) == spec["agent"]["replica_bounds"]


def test_build_guardrails_autonomy_override():
    assert build_guardrails({}, autonomy="L1").autonomy == "L1"


def test_rca_summary_fallback_without_client():
    out = rca_summary(None, {"health_ok": False, "pod_reason": "CrashLoopBackOff"})
    assert "CrashLoopBackOff" in out


class _FakeActuator:
    def __init__(self): self.calls = []
    def execute(self, action, params): self.calls.append(action)


def test_canary_check_keeps_when_healthy():
    act = _FakeActuator()
    kept = canary_check(lambda: {"health_ok": True}, act, client=None, record=_silent)
    assert kept is True and act.calls == []


def test_canary_check_rolls_back_when_unhealthy():
    act = _FakeActuator()
    kept = canary_check(lambda: {"health_ok": False, "pod_reason": "CrashLoopBackOff"},
                        act, client=None, record=_silent)
    assert kept is False and act.calls == ["rollback"]


class _RaisingActuator:
    def execute(self, action, params):
        raise RuntimeError("no prior revision")  # e.g. first deploy


def test_canary_check_tolerates_rollback_failure():
    # a first-deploy rollback failure must not crash — just report unhealthy
    kept = canary_check(lambda: {"health_ok": False}, _RaisingActuator(),
                        client=None, record=_silent)
    assert kept is False


@pytest.mark.parametrize("signals,expected", [
    ({"pod_reason": "ImagePullBackOff"}, "redeploy"),
    ({"pod_reason": "Pending"}, "scale_nodes"),
    ({"pod_reason": "CrashLoopBackOff"}, "rollback"),
    ({"network_analysis": "dns"}, "restart_workload"),
    ({"error_rate_rising": True}, "run_network_analysis"),
    ({}, "hold"),
])
def test_rule_based_mapping(signals, expected):
    assert rule_based(signals)["action"] == expected


def test_decide_uses_valid_model_action():
    client = ScriptedLLMClient(['{"action": "rollback", "diagnosis": "bad", "params": {}}'])
    out = decide(client, Guardrails(), {"pod_reason": "CrashLoopBackOff"})
    assert out["action"] == "rollback"
    assert out["source"] == "model"


def test_decide_rejects_off_allowlist_model_action():
    client = ScriptedLLMClient(['{"action": "delete_database", "params": {}}'])
    out = decide(client, Guardrails(), {"pod_reason": "CrashLoopBackOff"})
    assert out["action"] == "rollback"       # fell back to the deterministic rule
    assert out["source"] == "fallback"


def test_decide_without_model_uses_rules():
    out = decide(None, Guardrails(), {"pod_reason": "Pending"})
    assert out["action"] == "scale_nodes"


def test_loop_self_heals_crashloop():
    cluster = SimulatedCluster(pod_reason="CrashLoopBackOff", healthy=False)
    actuator = SimulatedActuator(cluster)
    ok = run_loop(SimulatedSignals(cluster).snapshot, actuator, Guardrails(autonomy=L2_ACT),
                  client=None, record=_silent)
    assert ok
    assert "rollback" in [a for a, _ in actuator.history]
    assert cluster.is_healthy()


def test_loop_investigates_then_restarts_on_rising_errors():
    cluster = SimulatedCluster(error_rate_rising=True, healthy=False)
    actuator = SimulatedActuator(cluster)
    ok = run_loop(SimulatedSignals(cluster).snapshot, actuator, Guardrails(autonomy=L2_ACT),
                  client=None, record=_silent)
    assert ok
    actions = [a for a, _ in actuator.history]
    assert actions[0] == "run_network_analysis"
    assert "restart_workload" in actions


def test_loop_L1_escalates_without_acting():
    cluster = SimulatedCluster(pod_reason="CrashLoopBackOff", healthy=False)
    actuator = SimulatedActuator(cluster)
    escalated = {}
    ok = run_loop(SimulatedSignals(cluster).snapshot, actuator, Guardrails(autonomy=L1_RECOMMEND),
                  client=None, on_escalate=escalated.update, record=_silent)
    assert ok is False
    assert actuator.history == []               # took no action
    assert escalated["action"] == "rollback"    # but recommended one


def test_loop_escalates_after_retry_budget():
    # A fault the actuator never fixes -> agent gives up after the budget.
    calls = {"n": 0}

    def observe():
        calls["n"] += 1
        return {"pod_reason": "CrashLoopBackOff", "health_ok": False}

    class DeadActuator:
        def execute(self, action, params):
            return {}

    escalated = {}
    ok = run_loop(observe, DeadActuator(), Guardrails(autonomy=L2_ACT, retry_budget=3),
                  client=None, on_escalate=escalated.update, record=_silent)
    assert ok is False
    assert escalated["action"] == "escalate"
