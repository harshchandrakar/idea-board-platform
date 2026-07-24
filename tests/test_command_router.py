from ai import command_router as cr
from ai.llm_client import ScriptedLLMClient


def test_rule_based_preview():
    assert cr.rule_based_route("spin up a preview")["command"] == "deploy-preview"
    assert cr.rule_based_route("give me a link to try it")["command"] == "deploy-preview"


def test_rule_based_down():
    assert cr.rule_based_route("tear it down")["command"] == "preview-down"
    assert cr.rule_based_route("delete the preview")["command"] == "preview-down"


def test_rule_based_status():
    assert cr.rule_based_route("what's the status?")["command"] == "preview-status"


def test_rule_based_unknown_is_help():
    assert cr.rule_based_route("make me a sandwich")["command"] == "help"


def test_route_rejects_off_allowlist_command():
    # even if the model tries a production action, it's not on the menu -> fallback
    client = ScriptedLLMClient(['{"command": "rollback", "params": {}}'])
    d = cr.route("roll back production", client)
    assert d["command"] in cr.ALLOWED_COMMANDS
    assert d["command"] != "rollback"        # rollback isn't even selectable


def test_no_production_commands_in_allowlist():
    # structural guarantee: nothing that can touch prod
    for banned in ("rollback", "scale", "deploy-backend", "deploy-frontend"):
        assert banned not in cr.ALLOWED_COMMANDS


def test_generated_commands_are_preview_scoped_only():
    # every command targets idea-pr-<n>, never the production release "idea"
    for cmd in ("deploy-preview", "preview-status", "preview-down"):
        cmds = cr.generate_commands({"command": cmd}, pr="42")
        joined = " ".join(cmds)
        assert "idea-pr-42" in joined
        # must NOT operate on the production release/namespace
        assert " idea " not in joined and "-n idea " not in joined
        assert "uninstall idea " not in joined


def test_markdown_notes_production_safety():
    md = cr.as_markdown("preview", cr.rule_based_route("preview"), pr="7")
    assert "idea-pr-7" in md and "Production-safe" in md
