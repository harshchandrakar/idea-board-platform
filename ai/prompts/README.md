# ai/prompts/ — the text we send to the model, kept out of the code

Each `.txt` file is one prompt template with `{{placeholder}}` tokens. Python
loads them via `ai.prompts.render(name, **values)` and substitutes the values.

Why prompts live here and not inline in the `.py` files:

- **Editable without touching code** — tune the wording and re-run; no logic changes.
- **Reviewable** — a prompt change is a clean, readable diff.
- **Reusable** — the same template can be used from several call sites.

| File | Used by | Purpose |
|---|---|---|
| `iac_generate.txt` | `iac_generator.build_brief()` | Ground the model to generate safe Terraform (allowlist, pinned module, size map, required outputs). |
| `agent_decide.txt` | `agent.decide()` | Ask the operator-agent to pick ONE allowlisted action from the signals. |
| `summarize.txt` | `summarize.py` | Plain-English "what's shipping" for reviewers. |
| `propose_config.txt` | `propose_config.py` | Turn a plain-English goal into concrete sizing numbers. |

Tokens use `{{name}}` (not Python `str.format`) on purpose: the prompts contain
literal JSON like `{"action": ...}`, and `.format()` would break on those braces.
