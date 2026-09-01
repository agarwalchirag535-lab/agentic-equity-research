"""Run one agent end-to-end: prompt → provider → schema-validated output (Law 4).

On a schema violation the runner retries with the validation error appended (max 2 retries), then hard
fails with the error — never returns free prose.

THE ENVELOPE IS NOT THE ANSWER (ADR-0075). A real provider rarely returns a bare JSON object: the
`claude -p` CLI that the no-API-key path depends on habitually wraps it in a ```json fence, and most
chat models add a line of preamble. Validating the raw text alone failed those replies for their
punctuation rather than their content, burned all three attempts and raised — so the firm's primary
free path could break on formatting while the agent's actual answer was correct.

Tolerating the envelope loosens nothing that matters: the extracted object still has to satisfy the
Pydantic schema (Law 4), and every downstream gate — the numeric discipline, the scenario grid check,
the citation validator — runs exactly as before on what comes out.
"""

from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from firm.core.llm.provider import LLMRequest, Provider

T = TypeVar("T", bound=BaseModel)

#: ```json ... ``` or ``` ... ```, the shape every chat model reaches for when asked to emit JSON.
_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)


class AgentValidationError(RuntimeError):
    """Raised when an agent's output fails schema validation after all retries."""


def candidate_payloads(text: str) -> list[str]:
    """The response, then progressively less of its envelope — most literal reading first.

    Order matters and is the conservative direction: a reply that IS the JSON object is used as-is, and
    only a reply that is not gets unwrapped. The brace scan takes the outermost balanced pair, so a JSON
    object quoted inside the agent's own prose cannot displace the real answer that encloses it.
    """
    stripped = text.strip()
    out = [stripped]
    out += [m.group(1).strip() for m in _FENCE.finditer(stripped)]

    start, depth = stripped.find("{"), 0
    if start != -1:
        for i in range(start, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(stripped[start:i + 1])
                    break
    # Deduplicate, keeping order: an unfenced bare object yields the same string three times.
    return list(dict.fromkeys(c for c in out if c))


def run_agent(
    provider: Provider,
    *,
    system: str,
    user: str,
    model: str,
    schema: type[T],
    temperature: float = 0.2,
    max_retries: int = 2,
) -> T:
    prompt = user
    last_error: ValidationError | None = None
    for _ in range(max_retries + 1):
        resp = provider.complete(
            LLMRequest(system=system, prompt=prompt, model=model, temperature=temperature)
        )
        err: ValidationError | None = None
        for payload in candidate_payloads(resp.text):
            try:
                return schema.model_validate_json(payload)
            except ValidationError as exc:
                err = err or exc          # report the failure of the most literal reading
        if err is not None:
            last_error = err
            prompt = (
                f"{user}\n\nYour previous reply failed schema validation:\n{err}\n"
                "Return ONLY a single JSON object matching the required schema."
            )
    raise AgentValidationError(
        f"agent output failed validation after {max_retries + 1} attempts"
    ) from last_error
