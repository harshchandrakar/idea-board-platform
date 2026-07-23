#!/usr/bin/env bash
# Shift 100% of traffic to the canary release, then make it the new stable.
set -euo pipefail
echo "[promote] promoting canary to stable"
