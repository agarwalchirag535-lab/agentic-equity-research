"""A plain DAG runner (SPEC §9: 'do not reach for a heavy framework in Phase 1').

Each task is keyed by a content hash so re-running is free and a crash resumes where it stopped (Law 5).
State is explicit — results flow task→task as a dict, never as natural language.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from firm.core.llm.cache import make_key


@dataclass(frozen=True)
class Task:
    id: str
    deps: tuple[str, ...]
    run: Callable[[dict[str, Any]], Any]
    version: str = "1.0.0"


def _topo_order(tasks: dict[str, Task]) -> list[str]:
    """Kahn's algorithm; raises on a cycle or an unknown dependency."""
    indeg = {tid: 0 for tid in tasks}
    for t in tasks.values():
        for d in t.deps:
            if d not in tasks:
                raise ValueError(f"task {t.id!r} depends on unknown task {d!r}")
            indeg[t.id] += 1
    ready = [tid for tid, n in indeg.items() if n == 0]
    order: list[str] = []
    while ready:
        tid = ready.pop()
        order.append(tid)
        for t in tasks.values():
            if tid in t.deps:
                indeg[t.id] -= 1
                if indeg[t.id] == 0:
                    ready.append(t.id)
    if len(order) != len(tasks):
        raise ValueError("cycle detected in task graph")
    return order


def run_dag(
    tasks: list[Task],
    *,
    as_of: str,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute tasks in dependency order. ``cache`` (task-key -> result) enables resume: a task whose
    key is already present is skipped."""
    cache = cache if cache is not None else {}
    index = {t.id: t for t in tasks}
    results: dict[str, Any] = {}
    for tid in _topo_order(index):
        t = index[tid]
        key = make_key(t.id, t.version, as_of, *sorted(t.deps))
        if key in cache:
            results[tid] = cache[key]
            continue
        inputs = {d: results[d] for d in t.deps}
        out = t.run(inputs)
        cache[key] = out
        results[tid] = out
    return results
