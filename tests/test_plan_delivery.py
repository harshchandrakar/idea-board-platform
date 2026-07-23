import os

from ai import plan_delivery as pd
from ai.llm_client import ScriptedLLMClient

ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = pd.load_spec(os.path.join(ROOT, "platform.json"))


def test_free_aws_goal_picks_free_tier():
    p = pd.rule_based_plan("free aws demo", SPEC)
    assert p["cloud"] == "aws"
    assert p["target"] == "free-tier-vm"
    assert p["environment"] == "staging"


def test_production_gcp_goal_picks_managed():
    p = pd.rule_based_plan("production on gcp", SPEC)
    assert p["cloud"] == "gcp"
    assert p["target"] == "managed-cloud"
    assert p["environment"] == "production"


def test_gcp_free_goal_picks_free_tier_vm():
    # gcp now has a free_tier_target (Always Free e2-micro)
    p = pd.rule_based_plan("cheap gcp demo", SPEC)
    assert p["cloud"] == "gcp"
    assert p["target"] == "free-tier-vm"


def test_validate_rejects_unknown_cloud():
    problems = pd.validate_plan(
        {"cloud": "azure", "target": "managed-cloud", "environment": "staging"}, SPEC)
    assert any("azure" in p for p in problems)


def test_validate_rejects_target_not_offered_for_cloud():
    # Construct a spec where gcp offers no free tier, then a free-tier pick is invalid.
    import copy
    spec = copy.deepcopy(SPEC)
    spec["delivery"]["clouds"]["gcp"]["free_tier_target"] = None
    problems = pd.validate_plan(
        {"cloud": "gcp", "target": "free-tier-vm", "environment": "staging"}, spec)
    assert any("not offered for cloud" in p for p in problems)


def test_plan_uses_valid_model_choice():
    client = ScriptedLLMClient(
        ['{"cloud": "aws", "target": "managed-cloud", "environment": "production", "reason": "x"}'])
    p = pd.plan("go big on aws", SPEC, client=client)
    assert p["cloud"] == "aws" and p["target"] == "managed-cloud"
    assert p["source"] == "model"


def test_plan_rejects_off_allowlist_model_choice():
    # model hallucinates an unknown target -> fall back to rules
    client = ScriptedLLMClient(
        ['{"cloud": "gcp", "target": "serverless-magic", "environment": "staging"}'])
    p = pd.plan("free gcp", SPEC, client=client)
    assert p["source"] == "fallback"
    assert p["target"] == "free-tier-vm"        # the safe, valid choice for gcp
