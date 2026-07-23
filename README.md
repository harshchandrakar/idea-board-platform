# Idea Board — an AI-first, cloud-agnostic DevOps platform

A tiny app (React + FastAPI + Postgres) plus the real deliverable: a platform that
builds, deploys, verifies, and self-heals it — driven by one JSON file, with an
AI **deployment agent** that operates within strict guardrails.

> The full plain-language design doc is `BLUEPRINT.md` (separate). This README is the
> practical getting-started and a map of the repo.

## The one idea: plug into sockets, not walls

Everything swappable sits behind a small contract:

- **Cloud** — described once in `platform.json`; the LLM *generates* each cloud's
  Terraform on demand and a validation gauntlet proves it safe before apply.
- **Orchestrator** — Kubernetes/Helm, reached through an `Actuator` interface.
- **AI** — an `LLMClient` (reasoning) + `Actuator` (acting), so the model and the
  execution target are each swappable.
- **Observability** — OpenTelemetry, fanned out to LangSmith (agent traces) and a
  metrics backend. Swap backends with one line.

## Repository map

```
platform.json          single source of truth: app, envs, sizing, provider templates, policy
app/backend            FastAPI service (GET/POST /api/ideas, /api/health)
app/frontend           React (Vite) UI
docker-compose.yml     full local stack
ai/                    the deployment agent
  llm_client.py          reasoning socket (Gemini plug + scripted stub + ask_json)
  actions.py             acting socket: Actuator + K8sActuator + SimulatedActuator
  guardrails.py          ALLOWLIST + Guardrails + clamp/allowlist/autonomy enforcement
  signals.py             read-only signal collector (+ simulated source)
  agent.py               observe -> diagnose -> act -> verify loop (+ runnable demo)
  iac_generator.py       generate Terraform from platform.json + deterministic checks
  canary.py              canary start/promote/abort
  telemetry.py           decision records via OpenTelemetry (LangSmith) + structured logs
deploy/helm            portable Kubernetes manifests (+ watcher CronJob, OTel collector)
infra/policy           OPA/conftest policy (gate 4 of the gauntlet)
infra/generated        LLM-generated Terraform (committed, reviewable; do not hand-edit)
.github/workflows      CI/CD: summary -> config -> build -> generate+validate -> apply -> canary+agent
tests/                 pytest suite (agent, guardrails, actuator, iac, signals, backend)
```

## Quick start

### Fastest: one command (checks/installs Docker, runs everything)
```bash
./run-local.sh            # add -y to skip install prompts
```
This checks for Docker + Compose (installing Docker if missing), builds and starts
the full stack, waits for health, and runs a smoke test against the API. Useful flags:
`--check` (only report prerequisites), `--tests` (also run pytest), `--demo` (run the
agent self-heal demo), `--down` (stop the stack), `--help`.

### Or run the app directly with Compose
```bash
docker compose up --build
# Frontend: http://localhost:3000   API: http://localhost:8000/api/health
```
Or without Docker:
```bash
# backend
cd app/backend && pip install -r requirements.txt && uvicorn main:app --reload
# frontend (new terminal)
cd app/frontend && npm install && VITE_API_URL=http://localhost:8000 npm run dev
```
The backend defaults to a local SQLite file if `DATABASE_URL` is unset, so it runs
with zero setup; compose and the cloud set it to Postgres.

### Run the tests
```bash
pip install -r requirements-dev.txt
pytest -q
```

### Watch the agent self-heal (no cloud, no API key needed)
```bash
python -m ai.agent demo
```
This runs the full loop against a simulated cluster: a crash-looping release gets
rolled back; a rising error rate triggers a read-only network analysis and then a
targeted restart; and at autonomy **L1** the agent escalates instead of acting.

## Deploy to a cloud (CI)

1. Store secrets in GitHub Actions: cloud credentials, `GEMINI_API_KEY`, a container
   registry, and (optional) `LANGSMITH_API_KEY`.
2. Run the **Deploy Idea Board** workflow, choosing `cloud` and `environment`.
3. The pipeline: AI summary → sizing → build images → **generate IaC from
   `platform.json` → validation gauntlet** → apply → canary → the agent promotes,
   repairs, or rolls back.

**Add a cloud** = add one block under `providers` in `platform.json`. No `.tf` files
to write by hand.

## The IaC safety gauntlet (why LLM-generated infra is safe here)

Generated Terraform is *guilty until proven valid*. Before anything applies it must pass:
`terraform fmt` → `terraform validate` → `terraform plan` → **policy** (`conftest`
against `infra/policy`) → **contract** (the 3 required outputs) → **destroy-guard**
(`ai/iac_generator.py assert-nondestructive` refuses to auto-apply a plan that would
destroy/replace a protected resource). On failure it does RCA, fixes, and regenerates
up to a budget, then escalates. The model may only use resource/module types on the
provider's `allowed_resources` list — it fills structure, it never invents pieces.

## Verification status (what was actually tested)

Verified in a sandbox with `pytest`, `node`, `helm`, and `terraform`:

- **Backend** — live server: `/api/health`, create + list ideas, empty-content → 422.
- **Agent logic** — 48 unit tests: allowlist enforcement, param clamping, autonomy
  gating, deterministic fallback, off-allowlist rejection, the full self-heal loop,
  escalation on budget exhaustion, actuator command construction, signal parsing.
- **Agent end-to-end** — the `demo` runs three scenarios green.
- **IaC** — deterministic checks (allowlist, contract, destroy-guard) unit-tested;
  a representative stack passes real `terraform validate`/`plan`, and the destroy-guard
  correctly blocks a protected-DB replace on a real plan JSON.
- **Helm chart** — `helm lint` clean; `helm template` renders all manifests.
- **Frontend** — `npm run build` succeeds (Vite production build).
- **Configs** — `platform.json` and the YAML files parse.

Requires a real cloud account / cluster / `GEMINI_API_KEY` to run (not testable in a
sandbox): live `terraform apply` against AWS/GCP, `kubectl`/`helm` against a real
cluster, canary traffic shifting, and live Gemini calls. The code paths for these are
present and structured so their command construction is unit-tested; the pipeline runs
them in CI.
# idea-board-platform
