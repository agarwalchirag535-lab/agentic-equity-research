"""Every numeric field an agent can return must be classified, or the build fails.

The hole this closes: `_numeric_discipline` validates only fields present in `NUMERIC_FIELD_SOURCES`,
and the citation validator walks only strings — so a numeric schema field in neither place is a number
nobody checks. The whole judgment tier's numeric fields sat in that gap, latent only because Phase 4 had
not run. This test makes the gap impossible to reopen: a new numeric field fails the build until someone
decides what it is — a financial number (registered, with its compute source or an explicit null-only
entry) or a bounded judgment score (allowlisted by class and name).
"""

from __future__ import annotations

import typing

from pydantic import BaseModel

from firm.core.pipeline.deep_dive import (
    JUDGMENT_NUMERIC_FIELDS,
    NESTED_COMPUTED_FIELDS,
    NUMERIC_FIELD_SOURCES,
)
from firm.schemas.agents import AGENT_OUTPUTS


def _numeric_leaves(annotation: object) -> bool:
    """Whether this annotation can hold an int or float (bool excluded — it is not a quantity)."""
    origin = typing.get_origin(annotation)
    if origin is not None:
        return any(_numeric_leaves(a) for a in typing.get_args(annotation) if a is not type(None))
    return isinstance(annotation, type) and issubclass(annotation, (int, float)) \
        and not issubclass(annotation, bool)


def _nested_models(annotation: object) -> list[type[BaseModel]]:
    origin = typing.get_origin(annotation)
    if origin is not None:
        return [m for a in typing.get_args(annotation) if a is not type(None)
                for m in _nested_models(a)]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return []


def _collect(model: type[BaseModel], top_level: bool, seen: set[type[BaseModel]],
             direct: set[str], nested: set[str]) -> None:
    if model in seen:
        return
    seen.add(model)
    for name, field in model.model_fields.items():
        if _numeric_leaves(field.annotation):
            (direct if top_level else nested).add(name if top_level else f"{model.__name__}.{name}")
        for sub in _nested_models(field.annotation):
            _collect(sub, top_level=False, seen=seen, direct=direct, nested=nested)


def test_every_numeric_agent_field_is_registered_or_classified_as_judgment():
    direct: set[str] = set()
    nested: set[str] = set()
    for output in AGENT_OUTPUTS.values():
        _collect(output, top_level=True, seen=set(), direct=direct, nested=nested)

    unregistered = direct - set(NUMERIC_FIELD_SOURCES)
    assert not unregistered, (
        f"numeric agent fields with NO validator behind them: {sorted(unregistered)}. Register each in "
        f"NUMERIC_FIELD_SOURCES — with its derived-metric source, or None if the agent must return null."
    )

    unclassified = nested - (JUDGMENT_NUMERIC_FIELDS | NESTED_COMPUTED_FIELDS)
    assert not unclassified, (
        f"nested numeric fields that are neither validated nor classified as judgment scores: "
        f"{sorted(unclassified)}. Add to JUDGMENT_NUMERIC_FIELDS only if a bounded judgment; a "
        f"financial number needs top-level registration and a compute source instead."
    )


def test_the_registry_names_no_field_that_does_not_exist():
    """A registry entry for a renamed field silently validates nothing — the hole in a new disguise."""
    direct: set[str] = set()
    for output in AGENT_OUTPUTS.values():
        _collect(output, top_level=True, seen=set(), direct=direct, nested=set())
    ghosts = set(NUMERIC_FIELD_SOURCES) - direct
    assert not ghosts, f"NUMERIC_FIELD_SOURCES entries matching no agent schema field: {sorted(ghosts)}"
