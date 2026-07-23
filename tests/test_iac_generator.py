import json
import os

from ai import iac_generator as iac
from ai.llm_client import ScriptedLLMClient

ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = os.path.join(ROOT, "platform.json")

GOOD_TF = '''
module "eks" { source = "terraform-aws-modules/eks/aws" }
resource "aws_db_instance" "pg" { engine = "postgres" }
output "kubeconfig"   { value = "x" }
output "database_url" { value = "y" }
output "app_endpoint" { value = "z" }
'''

BAD_TF = '''
resource "aws_s3_bucket" "leak" { acl = "public-read" }
output "kubeconfig" { value = "x" }
'''


def test_load_spec_and_sizing():
    spec = iac.load_spec(SPEC)
    assert spec["app"]["name"] == "idea-board"
    assert iac.sizing_for(spec, "staging")["node_size"] == "small"
    assert iac.sizing_for(spec, "production")["node_size"] == "medium"


def test_allowlist_passes_good_tf():
    spec = iac.load_spec(SPEC)
    allowed = spec["providers"]["aws"]["allowed_resources"]
    assert iac.check_allowlist(GOOD_TF, allowed) == []


def test_allowlist_flags_disallowed_resource():
    spec = iac.load_spec(SPEC)
    allowed = spec["providers"]["aws"]["allowed_resources"]
    violations = iac.check_allowlist(BAD_TF, allowed)
    assert any("aws_s3_bucket" in v for v in violations)


def test_contract_check():
    assert iac.check_contract(GOOD_TF) == []
    missing = iac.check_contract(BAD_TF)
    assert "database_url" in missing and "app_endpoint" in missing


def test_assert_nondestructive_blocks_db_delete():
    plan = {"resource_changes": [
        {"address": "aws_db_instance.pg", "type": "aws_db_instance",
         "change": {"actions": ["delete", "create"]}},
    ]}
    issues = iac.assert_nondestructive(plan, ["aws_db_instance"])
    assert len(issues) == 1


def test_assert_nondestructive_allows_create_only():
    plan = {"resource_changes": [
        {"address": "aws_db_instance.pg", "type": "aws_db_instance",
         "change": {"actions": ["create"]}},
    ]}
    assert iac.assert_nondestructive(plan, ["aws_db_instance"]) == []


def test_generate_writes_file(tmp_path):
    spec = iac.load_spec(SPEC)
    client = ScriptedLLMClient([GOOD_TF])
    path = iac.generate(spec, "aws", "staging", client=client, out_dir=str(tmp_path))
    assert os.path.exists(path)
    tf = open(path, encoding="utf-8").read()
    assert 'output "kubeconfig"' in tf
    # the brief we sent grounds the model with the allowlist + contract
    brief = client.calls[0]
    assert "use ONLY these resource/module types" in brief
    assert "kubeconfig" in brief
