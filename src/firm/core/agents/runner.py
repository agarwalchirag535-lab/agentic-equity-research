"""Run one agent end-to-end: prompt → provider → schema-validated output (Law 4).

On a schema violation the runner retries with the validation error appended (max 2 retries), then hard
fails with the error — never returns free prose.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from firm.core.llm.provider import LLMRequest, Provider

T = TypeVar("T", bound=BaseModel)


class AgentValidationError(RuntimeError):
    """Raised when an agent's output fails schema validation after all retries."""


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
        try:
            return schema.model_validate_json(resp.text)
        except ValidationError as err:
            last_error = err
            prompt = (
                f"{user}\n\nYour previous reply failed schema validation:\n{err}\n"
                "Return ONLY a single JSON object matching the required schema."
            )
    raise AgentValidationError(
        f"agent output failed validation after {max_retries + 1} attempts"
    ) from last_error
