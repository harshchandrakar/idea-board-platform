#!/usr/bin/env bash
# Delete GKE-orphaned L7 load-balancer resources that block VPC deletion.
#
# GKE provisions these (named k8s*) for Ingress/LoadBalancer Services OUTSIDE
# Terraform's knowledge, so `terraform destroy` can't remove the network until
# they're gone. Run this AFTER the cluster is deleted (so GKE won't recreate them),
# then retry the VPC delete. Idempotent and safe to run repeatedly.
set -uo pipefail

echo "[lb-cleanup] removing orphaned GKE load-balancer resources (k8s*) ..."
del() { echo "  - gcloud compute $*"; gcloud compute "$@" --quiet 2>/dev/null || true; }

# Delete in dependency order: forwarding-rule -> proxy -> url-map -> backend-service
# -> health-check / NEG, then firewall rules.
for f in $(gcloud compute forwarding-rules list --global --filter="name~k8s" --format="value(name)" 2>/dev/null); do del forwarding-rules delete "$f" --global; done
for p in $(gcloud compute target-http-proxies  list --filter="name~k8s" --format="value(name)" 2>/dev/null); do del target-http-proxies  delete "$p"; done
for p in $(gcloud compute target-https-proxies list --filter="name~k8s" --format="value(name)" 2>/dev/null); do del target-https-proxies delete "$p"; done
for u in $(gcloud compute url-maps            list --filter="name~k8s" --format="value(name)" 2>/dev/null); do del url-maps            delete "$u"; done
for b in $(gcloud compute backend-services    list --global --filter="name~k8s" --format="value(name)" 2>/dev/null); do del backend-services delete "$b" --global; done
for h in $(gcloud compute health-checks       list --filter="name~k8s" --format="value(name)" 2>/dev/null); do del health-checks       delete "$h"; done
gcloud compute network-endpoint-groups list --filter="name~k8s" --format="value(name,zone)" 2>/dev/null | while read -r n z; do
  [ -n "$n" ] && del network-endpoint-groups delete "$n" --zone="$z"
done
for fw in $(gcloud compute firewall-rules list --filter="name~k8s" --format="value(name)" 2>/dev/null); do del firewall-rules delete "$fw"; done

echo "[lb-cleanup] done."
