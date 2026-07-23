"""Read-only signal collection. Everything here observes; nothing mutates.

The agent calls snapshot() on each pass. The kubectl runner is injectable so
tests can feed fake pod JSON, and SimulatedSignals reads a SimulatedCluster.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request


def _kubectl_runner(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


class SignalCollector:
    def __init__(self, app_url: str, namespace: str = "idea", kubectl=_kubectl_runner):
        self.app_url = app_url.rstrip("/")
        self.ns = namespace
        self.kubectl = kubectl

    def snapshot(self) -> dict:
        return {
            "health_ok": self._health(),
            "error_rate_rising": self._error_rate_rising(),
            "pod_reason": self._bad_pod_reason(),
        }

    def _health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.app_url}/api/health", timeout=5) as r:
                return r.status == 200
        except Exception:
            return False

    def _error_rate_rising(self) -> bool:
        # In production this reads the ingress/metrics backend. Kept as a seam.
        return False

    def _bad_pod_reason(self):
        try:
            out = self.kubectl(["kubectl", "get", "pods", "-n", self.ns, "-o", "json"])
            data = json.loads(out or '{"items": []}')
        except Exception:
            return None
        for pod in data.get("items", []):
            status = pod.get("status", {})
            for cs in status.get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting") or {}
                if waiting.get("reason") in ("ImagePullBackOff", "CrashLoopBackOff"):
                    return waiting["reason"]
            if status.get("phase") == "Pending":
                return "Pending"
        return None


class SimulatedSignals:
    """Reads a SimulatedCluster so the whole loop can run with no dependencies."""

    def __init__(self, cluster):
        self.cluster = cluster

    def snapshot(self) -> dict:
        return {
            "health_ok": self.cluster.is_healthy(),
            "error_rate_rising": self.cluster.error_rate_rising,
            "pod_reason": self.cluster.pod_reason,
            "network_analysis": self.cluster.network_analysis,
        }
