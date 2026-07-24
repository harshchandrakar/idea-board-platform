# infra/ — the machines layer (generated from platform.json)

Separation of concerns: **this builds the cluster; Helm (`deploy/helm`) runs the
app on it.** You provision infra rarely; you deploy the app often.

```
infra/
├── templates/         # REFERENCE templates (hand-written, known-good)
│   ├── gke.tf         #   GKE cluster + autoscaling node pool
│   └── eks.tf         #   EKS cluster + autoscaling node group
├── generated/<cloud>/ # what the generator produces (adapted from the reference)
└── policy/            # OPA/conftest policy (gauntlet gate)
```

## How generation works
The **Infra** workflow runs `ai/iac_generator.py`, which:
1. reads `platform.json` (the chosen provider's region, machine size, node
   autoscaling min/max), and
2. hands the model the provider's **reference template** with an instruction to
   change *only* those values,
3. writes the result to `infra/generated/<cloud>/main.tf`, then
4. runs the gauntlet (`fmt → validate → plan → conftest → non-destructive`) before apply.

So to switch cloud or resize: **edit `platform.json`** (`providers`, `sizing`) —
never hand-edit `.tf`. Add a new cloud by adding a `providers.<name>` block plus a
reference template it can adapt.

Both templates create a cluster whose **worker machines autoscale** between
`min_nodes` and `max_nodes` as pods need room — underneath the app's HPA.

## One-time: a remote-state bucket
```bash
# GCP
gsutil mb -l asia-south1 gs://<you>-idea-tfstate      # -> secret GCP_TF_STATE_BUCKET
# AWS
aws s3 mb s3://<you>-idea-tfstate --region ap-south-1  # -> secret AWS_TF_STATE_BUCKET
```

## Create / destroy
**Infra — provision cluster** workflow: `cloud` = gcp/aws, `action` = apply/destroy.
It regenerates the `.tf` from the spec each run, so apply and destroy always match
the current `platform.json`.

## Cost
- **GKE**: zonal cluster (free control-plane tier) + small autoscaling nodes.
  Cheap; covered by the $300 trial credit.
- **EKS**: control plane ~$73/mo + NAT ~$32/mo + nodes. Not free.

Always `destroy` when done testing.
