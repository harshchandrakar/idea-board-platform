import json

from ai.signals import SignalCollector, SimulatedSignals
from ai.actions import SimulatedCluster


def _pods(reason=None, phase="Running"):
    container = {}
    if reason:
        container = {"state": {"waiting": {"reason": reason}}}
    return json.dumps({"items": [{
        "status": {"phase": phase, "containerStatuses": [container]},
    }]})


def test_detects_crashloop():
    sc = SignalCollector("http://x", kubectl=lambda cmd: _pods("CrashLoopBackOff"))
    assert sc._bad_pod_reason() == "CrashLoopBackOff"


def test_detects_pending():
    sc = SignalCollector("http://x", kubectl=lambda cmd: _pods(phase="Pending"))
    assert sc._bad_pod_reason() == "Pending"


def test_healthy_returns_none():
    sc = SignalCollector("http://x", kubectl=lambda cmd: _pods())
    assert sc._bad_pod_reason() is None


def test_bad_pod_reason_survives_kubectl_failure():
    def boom(cmd):
        raise RuntimeError("no cluster")
    sc = SignalCollector("http://x", kubectl=boom)
    assert sc._bad_pod_reason() is None


def test_simulated_signals_reflect_cluster():
    cluster = SimulatedCluster(pod_reason="CrashLoopBackOff", healthy=False)
    snap = SimulatedSignals(cluster).snapshot()
    assert snap["pod_reason"] == "CrashLoopBackOff"
    assert snap["health_ok"] is False
