import json
import os

from ai import iac_generator as iac
from ai.llm_client import ScriptedLLMClient

ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = os.path.join(ROOT, "platform.json")

# Representative generated GKE Terraform (matches the reference structure).
GOOD_TF = '''
resource "google_compute_network" "vpc" { name = "idea-board-vpc" }
resource "google_container_cluster" "primary" { name = "idea-board" }
resource "google_container_node_pool" "primary_nodes" { name = "idea-board-pool" }
output "cluster_name" { value = "idea-board" }
'''

# Off-allowlist: references a resource not present in the reference/allowlist.
BAD_TF = '''
resource "google_storage_bucket" "leak" { name = "oops" }
output "nothing" { value = "x" }
'''


def test_load_spec_and_sizing():
    spec = iac.load_spec(SPEC)
    assert spec["app"]["name"] == "idea-board"
    assert iac.sizing_for(spec, "staging")["node_size"] == "small"
    assert iac.sizing_for(spec, "production")["node_size"] == "medium"


def test_reference_is_included_in_brief():
    spec = iac.load_spec(SPEC)
    brief = iac.build_brief(spec, "gcp", "staging")
    # the reference template text is embedded (grounding), plus the target values
    assert "google_container_node_pool" in brief
    assert "asia-south1" in brief
    assert "e2-small" in brief          # machine type for node_size=small


def test_allowlist_passes_good_tf():
    spec = iac.load_spec(SPEC)
    allowed = spec["providers"]["gcp"]["allowed_resources"]
    assert iac.check_allowlist(GOOD_TF, allowed) == []


def test_allowlist_flags_disallowed_resource():
    spec = iac.load_spec(SPEC)
    allowed = spec["providers"]["gcp"]["allowed_resources"]
    violations = iac.check_allowlist(BAD_TF, allowed)
    assert any("google_storage_bucket" in v for v in violations)


def test_contract_check():
    assert iac.check_contract(GOOD_TF) == []          # has cluster_name
    assert "cluster_name" in iac.check_contract(BAD_TF)


def test_strip_code_fences_removes_markdown():
    fenced = "```terraform\nresource \"x\" \"y\" {}\n```"
    out = iac.strip_code_fences(fenced)
    assert "```" not in out
    assert out.startswith('resource "x" "y"')


def test_generate_strips_fences_before_writing(tmp_path):
    spec = iac.load_spec(SPEC)
    client = ScriptedLLMClient(["```terraform\n" + GOOD_TF + "\n```"])
    path = iac.generate(spec, "gcp", "staging", client=client, out_dir=str(tmp_path))
    tf = open(path, encoding="utf-8").read()
    assert "```" not in tf
    assert 'output "cluster_name"' in tf


def test_generate_writes_file(tmp_path):
    spec = iac.load_spec(SPEC)
    client = ScriptedLLMClient([GOOD_TF])
    path = iac.generate(spec, "gcp", "staging", client=client, out_dir=str(tmp_path))
    assert os.path.exists(path)
    assert 'output "cluster_name"' in open(path, encoding="utf-8").read()


def test_assert_nondestructive_blocks_protected_delete():
    plan = {"resource_changes": [
        {"address": "google_container_cluster.primary", "type": "google_container_cluster",
         "change": {"actions": ["delete", "create"]}},
    ]}
    issues = iac.assert_nondestructive(plan, ["google_container_cluster"])
    assert len(issues) == 1


def test_assert_nondestructive_allows_create_only():
    plan = {"resource_changes": [
        {"address": "google_container_cluster.primary", "type": "google_container_cluster",
         "change": {"actions": ["create"]}},
    ]}
    assert iac.assert_nondestructive(plan, ["google_container_cluster"]) == []
