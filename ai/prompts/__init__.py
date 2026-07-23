"""Prompt templates, kept out of the code.

Each `.txt` file here is a prompt with `{{placeholder}}` tokens. `render()` loads
a template and substitutes values. Keeping prompts as data (not Python strings)
means you can tweak how the model is instructed, review changes as clean diffs,
and reuse the same wording in several places — the same idea as platform.json.

Usage:
    from ai.prompts import render
    text = render("agent_decide", allowed=[...], signals="{...}")
"""
from __future__ import annotations

import os

_DIR = os.path.dirname(__file__)


def render(name: str, **values) -> str:
    """Load prompts/<name>.txt and replace each {{key}} with str(value).

    We use plain token replacement (not str.format) on purpose: the prompts
    contain literal JSON like {"action": ...}, and format() would choke on those
    braces. {{key}} tokens sidestep that entirely.
    """
    path = os.path.join(_DIR, f"{name}.txt")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text
