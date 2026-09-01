"""No module-private function may exist without a caller (ADR-0074).

Three separate defects of exactly one shape were found in a single day:

* `_scenario_discipline` — written by ADR-0062 to stop an agent inventing a return multiple, with a
  docstring calling that "the single easiest way to launder an invented number through this system".
  Never called. An agent could write "bull: 4.2x" beside a computed 0.03x and pass every gate.
* `cleared_a_positive` — the golden set's record of the firm's most expensive error, unused while
  `render()` recomputed its count inline, so the number was printed without ever naming the company.
* `resolve_due` and `brier_score` — the whole memory loop, tested since Phase 0 and called by nothing,
  so the firm logged forecasts for months and never learned whether it was right.

**A capability nothing calls is indistinguishable from one that does not exist**, and unit tests do
not catch it, because the unit works perfectly in isolation. The registry test
(`test_numeric_registry`) makes numeric-field coverage structural rather than remembered; this makes
call-site coverage structural in the same way, for the case with no legitimate exceptions.

Scope is deliberately narrow: module-level functions named with a single leading underscore. Those are
private by convention, so an uncalled one is dead code or a disconnected check — never a public API
someone else is expected to reach for. Public helpers are excluded precisely because "no caller yet"
is a defensible state for them, and a guard with a long allowlist teaches people to extend the
allowlist.
"""

from __future__ import annotations

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "firm"

#: Private module-level functions with no caller in their own module, and the reason each is allowed.
#: Empty, and it should stay that way — an entry here is a claim that dead code earns its place.
ALLOWED: dict[str, str] = {}


def _orphans() -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text()
        for node in ast.parse(source).body:          # module level only, not nested or methods
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("_") or node.name.startswith("__"):
                continue
            # One match is the `def` line itself; anything more is a use.
            if len(re.findall(rf"\b{re.escape(node.name)}\b", source)) <= 1:
                found.append((str(path.relative_to(SRC.parent.parent)), node.name, node.lineno))
    return found


def test_every_private_function_has_a_caller():
    orphans = [(f, n, ln) for f, n, ln in _orphans() if n not in ALLOWED]
    detail = "\n".join(f"  {f}:{ln}  {n}()" for f, n, ln in orphans)
    assert not orphans, (
        f"{len(orphans)} private function(s) exist with no caller in their own module:\n{detail}\n\n"
        "This is the ADR-0074 defect: a check nothing calls cannot fail, so it protects nothing. "
        "Either wire it to its call site, delete it, or add it to ALLOWED with the reason it should "
        "exist uncalled."
    )


def test_the_allowlist_stays_honest():
    """An allowlist entry for a function that no longer exists is a stale exemption someone will
    eventually reuse without noticing what it was for."""
    names = {n for _, n, _ in _orphans()}
    stale = sorted(set(ALLOWED) - names)
    assert not stale, f"ALLOWED names functions that are no longer orphaned (or gone): {stale}"
