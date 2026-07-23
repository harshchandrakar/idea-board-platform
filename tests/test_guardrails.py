from ai.guardrails import (
    Guardrails, clamp, is_allowed, needs_human,
    L0_OBSERVE, L1_RECOMMEND, L2_ACT, FORBIDDEN,
)


def test_allowlist_accepts_reversible_actions():
    g = Guardrails()
    assert is_allowed("rollback", g)
    assert is_allowed("scale_replicas", g)


def test_allowlist_rejects_unknown_and_forbidden():
    g = Guardrails()
    assert not is_allowed("rm_rf_everything", g)
    for bad in FORBIDDEN:
        assert not is_allowed(bad, g)


def test_allowlist_respects_per_env_subset():
    g = Guardrails(allowed={"hold", "rollback"})
    assert is_allowed("rollback", g)
    assert not is_allowed("scale_nodes", g)  # on global list but not enabled here


def test_forbidden_blocked_even_if_someone_adds_it():
    g = Guardrails(allowed={"delete_database"})  # mistake
    assert not is_allowed("delete_database", g)


def test_clamp_replicas_within_bounds():
    g = Guardrails(replica_bounds=(2, 8))
    assert clamp({"action": "scale_replicas", "params": {"replicas": 50}}, g)["params"]["replicas"] == 8
    assert clamp({"action": "scale_replicas", "params": {"replicas": 0}}, g)["params"]["replicas"] == 2


def test_clamp_nodes_capped():
    g = Guardrails(max_node_increase=2)
    assert clamp({"action": "scale_nodes", "params": {"delta": 9}}, g)["params"]["delta"] == 2


def test_clamp_survives_garbage_params():
    g = Guardrails()
    out = clamp({"action": "scale_replicas", "params": {"replicas": "lots"}}, g)
    assert out["params"]["replicas"] == g.replica_bounds[0]


def test_needs_human_rules():
    assert needs_human({"action": "escalate"}, Guardrails(autonomy=L2_ACT))
    assert needs_human({"action": "rollback"}, Guardrails(autonomy=L0_OBSERVE))
    assert needs_human({"action": "rollback"}, Guardrails(autonomy=L1_RECOMMEND))
    assert needs_human({"action": "rollback"}, Guardrails(autonomy=L2_ACT, require_approval={"rollback"}))
    assert not needs_human({"action": "rollback"}, Guardrails(autonomy=L2_ACT))
