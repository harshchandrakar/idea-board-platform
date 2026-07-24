# Progressive canary (Argo Rollouts + Prometheus + AI RCA)

The backend can deploy as a **true progressive canary**: traffic shifts
**20% → 50% → 100%**, and between steps Argo Rollouts asks **Prometheus** for the
backend's success rate. If the error rate climbs past the threshold, Argo
**aborts and rolls back to the previous version automatically** — and the deploy
workflow then asks Gemini for a plain-English **root-cause summary**.

This is opt-in (`progressive_canary = on` when you run **Deploy backend**), because
it needs two controllers installed in the cluster. Default deploys stay the
simpler rolling-deploy + health-gate path.

## How it works
```
new image ──► Argo Rollout ──► 20% traffic ──► [Prometheus success-rate ≥ 95%?]
                                   │  yes                 │ no
                                   ▼                      ▼
                              50% ──► [check] ──► 100%   abort + rollback ──► AI RCA
```
- `deploy/helm/templates/backend-rollout.yaml` — the `Rollout` with the canary steps.
- `deploy/helm/templates/analysis-template.yaml` — the Prometheus query that gates each step.
- Backend exposes `/metrics` (`http_requests_total{status,...}`) via
  prometheus-fastapi-instrumentator, which Prometheus scrapes.
- On abort, the workflow runs `python -m ai.agent rca` → Gemini RCA from pod
  signals + recent logs.

## One-time cluster setup

**1. Install Argo Rollouts:**
```bash
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
```

**2. Install Prometheus** (scraping the backend). Simplest:
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/prometheus -n prometheus --create-namespace
```
Make sure Prometheus scrapes the backend pods. The default Prometheus config
discovers pods with the `prometheus.io/scrape: "true"` annotation — or use a
ServiceMonitor if you installed kube-prometheus-stack. The backend serves metrics
on port 8000 at `/metrics`.

**3. Point the analysis at your Prometheus** — set in `platform.json`-driven Helm
values (or override at deploy): `rollout.prometheusAddress`. Default:
`http://prometheus-server.prometheus.svc.cluster.local`.

## Run it
**Deploy backend** workflow → `progressive_canary = on`. Watch the run: it prints
`rollout phase: Progressing → Healthy` (promoted) or `Degraded` (aborted → AI RCA).

You can also watch live in the cluster:
```bash
kubectl argo rollouts get rollout backend -n idea --watch
```

## Tuning (all in `deploy/helm/values.yaml` → `rollout`)
- `successThreshold` — min success fraction to keep promoting (default 0.95).
- `stepPauseSeconds` — soak time at each weight.
- `replicas` — needs a few (weighting is by pod count without a mesh).

## ⚠️ Honest notes
- The analysis query scopes by `namespace`. **Confirm the metric name + labels**
  match your Prometheus by checking the real output:
  ```bash
  kubectl -n idea exec deploy/backend -- \
    python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/metrics').read().decode())" | grep http_requests_total
  ```
  Adjust the query in `analysis-template.yaml` if your labels differ.
- Without a service mesh, traffic weighting is **approximate** (by pod ratio).
  For exact weighting add a traffic router (NGINX Ingress / Istio) — Argo supports both.
- This path has been validated for structure, not a live run — install the two
  controllers and test on the cluster before relying on it.
