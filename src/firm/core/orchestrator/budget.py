"""Per-run cost ceiling (SPEC §9). The run aborts and reports on breach."""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetGuard:
    ceiling_usd: float
    spent_usd: float = 0.0
    ledger: list[tuple[str, float]] = field(default_factory=list)

    def charge(self, label: str, usd: float) -> None:
        if usd < 0:
            raise ValueError("charge cannot be negative")
        self.spent_usd += usd
        self.ledger.append((label, usd))
        if self.spent_usd > self.ceiling_usd:
            raise BudgetExceeded(
                f"run cost ${self.spent_usd:.4f} exceeded ceiling ${self.ceiling_usd:.4f} at {label!r}"
            )

    @property
    def remaining_usd(self) -> float:
        return self.ceiling_usd - self.spent_usd
