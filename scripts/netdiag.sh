#!/usr/bin/env bash
# Read-only network diagnostics: connectivity, DNS, DB reachability, ingress.
# Placeholder — wire to your cluster's tooling. Must NOT change anything.
set -euo pipefail
NS="${1:-idea}"
echo "[netdiag] checking DNS, service endpoints and DB reachability in ns=$NS"
