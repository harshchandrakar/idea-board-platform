import pytest

from ai.actions import K8sActuator, SimulatedActuator, SimulatedCluster


class Capture:
    def __init__(self):
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        return "ok"


def test_redeploy_builds_rollout_restart():
    cap = Capture()
    K8sActuator(namespace="idea", runner=cap).execute("redeploy", {})
    assert cap.cmds[-1] == ["kubectl", "rollout", "restart", "deployment", "-n", "idea"]


def test_scale_replicas_command():
    cap = Capture()
    K8sActuator(runner=cap).execute("scale_replicas", {"workload": "backend", "replicas": 4})
    assert cap.cmds[-1] == ["kubectl", "scale", "deployment/backend", "--replicas=4", "-n", "idea"]


def test_rollback_uses_helm():
    cap = Capture()
    K8sActuator(runner=cap).execute("rollback", {})
    assert cap.cmds[-1] == ["helm", "rollback", "idea", "-n", "idea"]


def test_hold_and_escalate_do_nothing():
    cap = Capture()
    act = K8sActuator(runner=cap)
    assert act.execute("hold", {})["ran"] is None
    assert act.execute("escalate", {})["ran"] is None
    assert cap.cmds == []


def test_unknown_action_refused():
    with pytest.raises(ValueError):
        K8sActuator(runner=Capture()).execute("format_disk", {})


def test_simulated_cluster_rollback_fixes_crashloop():
    cluster = SimulatedCluster(pod_reason="CrashLoopBackOff", healthy=False)
    SimulatedActuator(cluster).execute("rollback", {})
    assert cluster.is_healthy()


def test_simulated_network_analysis_is_readonly():
    cluster = SimulatedCluster(error_rate_rising=True, healthy=False)
    SimulatedActuator(cluster).execute("run_network_analysis", {})
    assert cluster.error_rate_rising is True          # still broken (read-only)
    assert cluster.network_analysis == "dns_failing_on_node"  # but cause revealed
