#!/usr/bin/env bash
# Increase the node pool by DELTA. Cloud-specific; kept behind the actuator.
set -euo pipefail
DELTA="${1:-1}"
echo "[scale_nodes] requesting +$DELTA node(s)"
