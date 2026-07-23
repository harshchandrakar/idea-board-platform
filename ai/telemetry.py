"""Observability for the agent's reasoning (Part G).

Every decision becomes a structured log line (always) and an OpenTelemetry span
(if the OTel packages are installed). Point the OTel exporter at LangSmith's OTLP
endpoint to get the rich trace view; the structured log line is your durable
audit trail regardless of any backend's retention.
"""
from __future__ import annotations

import json

try:  # pragma: no cover - optional dependency
    from opentelemetry import trace

    _tracer = trace.get_tracer("idea-agent")
except Exception:  # pragma: no cover
    _tracer = None


def _emit_log(payload: dict) -> None:
    # A single JSON line is easy to search and ship anywhere.
    print(json.dumps({"agent_decision": payload}, default=str))


def record_decision(signals: dict, decision: dict, guardrail: str, result: dict) -> None:
    payload = {
        "trigger": _trigger(signals),
        "source": decision.get("source", "model"),
        "action": decision.get("action"),
        "diagnosis": decision.get("diagnosis"),
        "params": decision.get("params"),
        "guardrail": guardrail,
        "confidence": decision.get("confidence"),
        "verified": result.get("verified"),
    }
    _emit_log(payload)
    if _tracer is None:
        return
    with _tracer.start_as_current_span("agent.decision") as span:  # pragma: no cover
        for key, value in payload.items():
            span.set_attribute(f"agent.{key}", str(value))


def _trigger(signals: dict) -> str:
    if signals.get("pod_reason"):
        return f"pod {signals['pod_reason']}"
    if signals.get("error_rate_rising"):
        return "error rate rising"
    if signals.get("network_analysis"):
        return f"analysis: {signals['network_analysis']}"
    return "routine check"
