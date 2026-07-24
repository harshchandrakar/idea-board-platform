#!/usr/bin/env bash
# Keyless GitHub->GCP auth via Workload Identity Federation (WIF).
# Creates a service account (NO key — sidesteps the org policy that blocks keys),
# grants it the roles the managed deploy needs, and lets ONLY your GitHub repo
# impersonate it over OIDC. Prints the two GitHub secrets to add at the end.
#
# Prereqs: gcloud installed + logged in (`gcloud auth login`), project selected
#          (`gcloud config set project <id>`).
#
# Usage:  bash scripts/gcp_wif_setup.sh <github-owner>/<repo>
#   e.g.  bash scripts/gcp_wif_setup.sh harsh/idea-board-platform
set -euo pipefail

REPO="${1:-}"
if [ -z "$REPO" ]; then
  echo "usage: bash scripts/gcp_wif_setup.sh <github-owner>/<repo>"; exit 1
fi

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA_NAME="idea-board-deployer"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github-pool"
PROVIDER="github-provider"

echo "==> Project: $PROJECT_ID ($PROJECT_NUMBER) | Repo: $REPO"

STATE_BUCKET="${PROJECT_ID}-idea-tfstate"

echo "==> [1/7] Enable required APIs"
gcloud services enable \
  iamcredentials.googleapis.com sts.googleapis.com iam.googleapis.com \
  compute.googleapis.com container.googleapis.com sqladmin.googleapis.com \
  servicenetworking.googleapis.com storage.googleapis.com

echo "==> [2/7] Create the service account (no key is ever created)"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="Idea Board deployer" 2>/dev/null || echo "    (already exists)"

echo "==> [3/7] Grant roles the deploy needs"
for ROLE in \
  roles/container.admin \
  roles/cloudsql.admin \
  roles/compute.admin \
  roles/iam.serviceAccountUser \
  roles/servicenetworking.networksAdmin \
  roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" --role="$ROLE" --condition=None >/dev/null
  echo "    + $ROLE"
done

echo "==> [3b] Create the Terraform state bucket (idempotent)"
gcloud storage buckets create "gs://${STATE_BUCKET}" \
  --location=asia-south1 --uniform-bucket-level-access 2>/dev/null \
  && gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning \
  || echo "    (bucket already exists)"

echo "==> [4/6] Create the workload identity pool"
gcloud iam workload-identity-pools create "$POOL" \
  --location="global" --display-name="GitHub Actions" 2>/dev/null || echo "    (pool exists)"

echo "==> [5/6] Create the GitHub OIDC provider (locked to your repo)"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --location="global" --workload-identity-pool="$POOL" \
  --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${REPO}'" 2>/dev/null \
  || echo "    (provider exists)"

echo "==> [6/6] Allow ONLY this repo to impersonate the service account"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" >/dev/null

PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"

cat <<EOF

✅ Done — no key was created. Add these GitHub repo secrets
   (Settings -> Secrets and variables -> Actions):

   GCP_WIF_PROVIDER      = ${PROVIDER_RESOURCE}
   GCP_SERVICE_ACCOUNT   = ${SA}
   GCP_TF_STATE_BUCKET   = ${STATE_BUCKET}

   (Also add GEMINI_API_KEY.)

Then: Actions -> Infra — provision cluster -> Run -> cloud=gcp, action=apply
      Actions -> Deploy backend / Deploy frontend -> Run -> cloud=gcp
Tear down later:  Infra workflow with action=destroy, then bash scripts/gcp_teardown.sh
EOF
