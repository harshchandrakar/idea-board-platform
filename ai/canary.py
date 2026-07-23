"""Minimal canary controller: release a new version to a small slice next to the
stable one, then promote or abort. Command construction is kept behind an
injectable runner so it is testable without a cluster.
"""
from __future__ import annotations

import subprocess


def _runner(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


class CanaryController:
    def __init__(self, release="idea", namespace="idea", runner=_runner):
        self.release, self.ns, self.run = release, namespace, runner

    def start(self, image_backend, image_frontend, database_url, weight=10):
        return self.run([
            "helm", "upgrade", "--install", f"{self.release}-canary", "deploy/helm",
            "-n", self.ns,
            "--set", f"image.backend={image_backend}",
            "--set", f"image.frontend={image_frontend}",
            "--set", f"databaseUrl={database_url}",
            "--set", f"canary.enabled=true",
            "--set", f"canary.weight={weight}",
            "--wait",
        ])

    def promote(self):
        return self.run(["bash", "scripts/promote_canary.sh", self.release])

    def abort(self):
        return self.run(["helm", "rollback", f"{self.release}-canary", "-n", self.ns])
