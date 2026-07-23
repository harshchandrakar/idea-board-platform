#!/usr/bin/env bash
# Tear down the free-tier deploy so nothing keeps costing money.
# Finds the EC2 instance by its Name tag, terminates it, and (once it's gone)
# deletes the security group. Requires the AWS CLI configured (`aws configure`).
#
# Usage:  bash scripts/aws_teardown.sh [name]      # default name: idea-board
set -euo pipefail

NAME="${1:-idea-board}"

echo "==> Looking for running/stopped instances tagged Name=$NAME ..."
IDS=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$NAME" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query "Reservations[].Instances[].InstanceId" --output text)

if [ -z "$IDS" ]; then
  echo "No matching instances. Nothing to terminate."
else
  echo "==> Terminating: $IDS"
  aws ec2 terminate-instances --instance-ids $IDS >/dev/null
  echo "==> Waiting for termination to complete ..."
  aws ec2 wait instance-terminated --instance-ids $IDS
  echo "    done."
fi

echo "==> Looking for a security group named '$NAME' ..."
SG=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$NAME" \
  --query "SecurityGroups[].GroupId" --output text 2>/dev/null || true)

if [ -n "$SG" ] && [ "$SG" != "None" ]; then
  echo "==> Deleting security group $SG"
  # brief retry loop — the SG can't be deleted until the ENI is fully released
  for i in 1 2 3 4 5 6; do
    if aws ec2 delete-security-group --group-id "$SG" 2>/dev/null; then
      echo "    deleted."; break
    fi
    echo "    still attached, retrying in 10s ($i/6) ..."; sleep 10
  done
else
  echo "    no matching security group (you may have named it differently)."
fi

echo
echo "✅ Teardown finished. Double-check in the console:"
echo "   EC2 → Instances (terminated), Volumes (gone), Security Groups, Key Pairs."
echo "   Billing → Free Tier shows usage; Cost Explorer should flatline."
