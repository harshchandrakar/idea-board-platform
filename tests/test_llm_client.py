from ai.llm_client import ScriptedLLMClient, ask_json


def test_ask_json_parses_plain_json():
    client = ScriptedLLMClient(['{"action": "hold", "confidence": 0.9}'])
    out = ask_json(client, "prompt", {"action": "fallback"})
    assert out["action"] == "hold"


def test_ask_json_strips_code_fences():
    client = ScriptedLLMClient(['```json\n{"action": "rollback"}\n```'])
    out = ask_json(client, "prompt", {"action": "fallback"})
    assert out["action"] == "rollback"


def test_ask_json_falls_back_on_bad_json():
    client = ScriptedLLMClient(["not json at all"])
    out = ask_json(client, "prompt", {"action": "fallback"})
    assert out == {"action": "fallback"}


def test_ask_json_falls_back_on_model_outage():
    client = ScriptedLLMClient(raise_error=RuntimeError("429 rate limited"))
    out = ask_json(client, "prompt", {"action": "fallback"})
    assert out == {"action": "fallback"}


def test_fallback_is_copied_not_shared():
    fb = {"action": "fallback"}
    out = ask_json(ScriptedLLMClient(["nope"]), "p", fb)
    out["mutated"] = True
    assert "mutated" not in fb  # caller's fallback dict is not mutated
