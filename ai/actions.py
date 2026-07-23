"""The acting socket. Executes exactly one allowlisted action.

K8sActuator drives Kubernetes/Helm. The command runner is injectable so tests
can assert the exact commands without a real cluster. SimulatedActuator lets the
whole loop run with no external dependency at all (used by the demo and tests).
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod


class Actuator(ABC):
    @abstractmethod
    def execute(self, action: str, params: dict) -> dict: ...


def _subprocess_runner(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return proc.stdout


class K8sActuator(Actuator):
    """Real actuator. Every branch maps to a reversible operation."""

    def __init__(self, namespace: str = "idea", runner=_subprocess_runner):
        self.ns = namespace
        self.run = runner  # injectable for tests

    def execute(self, action: str, params: dict) -> dict:
        params = params or {}
        ns = ["-n", self.ns]
        if action in ("hold", "escalate"):
            return {"ran": None}  # no cluster change
        if action == "redeploy":
            cmd = ["kubectl", "rollout", "restart", "deployment", *ns]
        elif action == "restart_workload":
            workload = params.get("workload", "backend")
            cmd = ["kubectl", "rollout", "restart", f"deployment/{workload}", *ns]
        elif action == "scale_replicas":
            workload = params.get("workload", "backend")
            replicas = int(params.get("replicas", 2))
            cmd = ["kubectl", "scale", f"deployment/{workload}", f"--replicas={replicas}", *ns]
        elif action == "scale_nodes":
            # Node-pool scaling is cloud-specific and stays behind this actuator.
            delta = int(params.get("delta", 1))
            cmd = ["bash", "scripts/scale_nodes.sh", str(delta)]
        elif action == "rollback":
            cmd = ["helm", "rollback", "idea", *ns]
        elif action == "abort_canary":
            cmd = ["helm", "rollback", "idea-canary", *ns]
        elif action == "promote_canary":
            cmd = ["bash", "scripts/promote_canary.sh"]
        elif action == "run_network_analysis":
            cmd = ["bash", "scripts/netdiag.sh", self.ns]
        else:
            raise ValueError(f"K8sActuator refuses unknown action: {action!r}")
        out = self.run(cmd)
        return {"ran": cmd, "output": out}


class SimulatedCluster:
    """A tiny in-memory cluster used by the demo and tests. It models the faults
    the agent is meant to heal and how each action resolves them.
    """

    def __init__(self, pod_reason=None, error_rate_rising=False, healthy=True):
        self.pod_reason = pod_reason
        self.error_rate_rising = error_rate_rising
        self.network_analysis = None
        self.healthy = healthy

    def is_healthy(self) -> bool:
        return self.healthy and self.pod_reason is None and not self.error_rate_rising

    def apply(self, action: str, params: dict) -> None:
        if action == "rollback" and self.pod_reason == "CrashLoopBackOff":
            self.pod_reason, self.healthy = None, True
        elif action == "redeploy" and self.pod_reason == "ImagePullBackOff":
            self.pod_reason, self.healthy = None, True
        elif action == "scale_nodes" and self.pod_reason == "Pending":
            self.pod_reason, self.healthy = None, True
        elif action == "run_network_analysis" and self.error_rate_rising:
            # read-only: reveals the cause but does not fix anything yet
            self.network_analysis = "dns_failing_on_node"
        elif action == "restart_workload" and self.network_analysis:
            self.error_rate_rising, self.network_analysis, self.healthy = False, None, True


class SimulatedActuator(Actuator):
    def __init__(self, cluster: SimulatedCluster):
        self.cluster = cluster
        self.history: list[tuple[str, dict]] = []

    def execute(self, action: str, params: dict) -> dict:
        self.history.append((action, dict(params or {})))
        self.cluster.apply(action, params or {})
        return {"ran": action, "healthy": self.cluster.is_healthy()}
