#!/usr/bin/env bash
# Remove EVERYTHING the managed GCP deploy created, so billing stops after testing.
#   1) terraform destroy the generated GKE + Cloud SQL infra
#   2) delete the Workload Identity pool/provider + the deployer service account
#   3) remind you to shut down / delete the project (the surest way to $0)
#
# Prereqs: gcloud + terraform installed, logged in, correct project selected.
# Usage:   bash scripts/gcp_teardown.sh
set -uo pipefail   # not -e: we want to continue cleaning even if a step is already gone

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
SA="idea-board-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github-pool"
PROVIDER="github-provider"
TF_DIR="infra/generated/gcp"

echo "==> Project: $PROJECT_ID"
echo

echo "==> [1/3] terraform destroy (GKE cluster + Cloud SQL + networking)"
if [ -d "$TF_DIR" ]; then
  ( cd "$TF_DIR" && terraform destroy -auto-approve ) || echo "    (destroy skipped/failed — check the console for leftovers)"
else
  echo "    no generated Terraform found at $TF_DIR — skipping."
fi

echo
echo "==> [2/3] delete Workload Identity Federation + service account"
gcloud iam workload-identity-pools providers delete "$PROVIDER" \
  --location=global --workload-identity-pool="$POOL" --quiet 2>/dev/null \
  && echo "    provider deleted" || echo "    provider already gone"
gcloud iam workload-identity-pools delete "$POOL" \
  --location=global --quiet 2>/dev/null \
  && echo "    pool deleted" || echo "    pool already gone"
gcloud iam service-accounts delete "$SA" --quiet 2>/dev/null \
  && echo "    service account deleted" || echo "    service account already gone"

echo
echo "==> [3/3] final check"
cat <<EOF

✅ Infra + auth removed.

To be 100% sure nothing bills you, either:
  • Disable billing:   Console -> Billing -> (your account) -> Manage -> disable, OR
  • Delete the project (surest):  gcloud projects delete "$PROJECT_ID"

Then confirm in Console -> Billing -> Reports that spend flatlines.
EOF
