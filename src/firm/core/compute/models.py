"""Business-model detection + playbook selection (ADR-0017 §1-2, ADAPTIVE_FORENSICS §4 step 4).

The owner directive this implements: *"there are n companies with different business structures; the model
should adapt itself based on those structures."* ADR-0012 established that forensic checks apply by
business model, not by sector label (a "used-car dealer" whose profit comes from loan sales is a lender).
This module generalises that: detect the model from the **shape of the statements**, then let a config
playbook decide which checks apply and which are suppressed.

Deterministic and offline (Law 1): shape ratios in, model tags out. No LLM decides what a company is.
A conglomerate legitimately matches several models — detection returns **all** matches (union of
playbooks), never a forced single label. When nothing matches, the result is empty and the caller must
fall back to the universal check set rather than guessing a model.

Thresholds live in `config/forensic_playbooks.yaml` and are **provisional** until the Phase-6 golden set
calibrates them (stated in ADR-0017).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum


class BusinessModel(str, Enum):
    LENDER = "LENDER"                 # NBFC / originate-to-sell / any material loan book
    BANK = "BANK"                     # deposit-taking lender
    MANUFACTURER = "MANUFACTURER"     # inventory + PPE intensive
    TRADER = "TRADER"                 # high revenue, near-zero gross margin, thin assets
    EPC_INFRA = "EPC_INFRA"           # contract assets / unbilled revenue / order book
    SERVICES_IT = "SERVICES_IT"       # people-heavy, low inventory, low PPE
    REAL_ESTATE = "REAL_ESTATE"       # inventory-as-property, customer advances


@dataclass(frozen=True)
class StatementShape:
    """Normalised detection inputs. Ratios are shares in [0,1] except `revenue_to_assets` (a turnover).

    `gross_margin` is `None` when not disclosed — never silently treated as zero, because "no margin
    disclosed" and "zero margin" mean very different things forensically.
    """

    loan_book_to_assets: float = 0.0
    interest_income_to_revenue: float = 0.0
    deposits_to_liabilities: float = 0.0
    inventory_to_assets: float = 0.0
    ppe_to_assets: float = 0.0
    contract_assets_to_assets: float = 0.0
    gross_margin: float | None = None
    revenue_to_assets: float = 0.0
    employee_cost_to_revenue: float = 0.0
    customer_advances_to_liabilities: float = 0.0


def detect_models(shape: StatementShape, t: Mapping[str, float]) -> list[BusinessModel]:
    """Every business model the statement shape matches, in declaration order (stable).

    Multiple tags are expected and correct for conglomerates: an auto company with a captive NBFC is
    both MANUFACTURER and LENDER, and must receive both playbooks.
    """
    tags: list[BusinessModel] = []

    is_lender = (
        shape.loan_book_to_assets >= t["lender_loan_book_min"]
        or shape.interest_income_to_revenue >= t["lender_interest_income_min"]
    )
    if is_lender:
        tags.append(BusinessModel.LENDER)
        if shape.deposits_to_liabilities >= t["bank_deposits_min"]:
            tags.append(BusinessModel.BANK)

    if (shape.inventory_to_assets >= t["manufacturer_inventory_min"]
            and shape.ppe_to_assets >= t["manufacturer_ppe_min"]):
        tags.append(BusinessModel.MANUFACTURER)

    if (shape.gross_margin is not None
            and shape.gross_margin <= t["trader_gross_margin_max"]
            and shape.revenue_to_assets >= t["trader_asset_turnover_min"]):
        tags.append(BusinessModel.TRADER)

    if shape.contract_assets_to_assets >= t["epc_contract_assets_min"]:
        tags.append(BusinessModel.EPC_INFRA)

    if (shape.employee_cost_to_revenue >= t["services_employee_cost_min"]
            and shape.inventory_to_assets <= t["services_inventory_max"]
            and shape.ppe_to_assets <= t["services_ppe_max"]):
        tags.append(BusinessModel.SERVICES_IT)

    if (shape.inventory_to_assets >= t["realestate_inventory_min"]
            and shape.customer_advances_to_liabilities >= t["realestate_advances_min"]):
        tags.append(BusinessModel.REAL_ESTATE)

    return tags


@dataclass(frozen=True)
class Playbook:
    """The resolved investigation plan for a company: which checks run, which are suppressed, and which
    notes to read first. `suppressed` always wins over `applies` — a check invalid for a model must never
    fire just because another matched model wanted it (e.g. Beneish on a bank)."""

    models: tuple[BusinessModel, ...]
    applies: tuple[str, ...]
    suppressed: tuple[str, ...]
    priority_notes: tuple[str, ...]

    def runs(self, check: str) -> bool:
        return check in self.applies and check not in self.suppressed


def build_playbook(
    models: Sequence[BusinessModel], config: Mapping[str, Mapping[str, Sequence[str]]]
) -> Playbook:
    """Union the per-model playbooks from config; suppression is global and takes precedence.

    `config` shape (from `forensic_playbooks.yaml`):
        {"UNIVERSAL": {"applies": [...]}, "LENDER": {"applies": [...], "suppress": [...], ...}, ...}
    The UNIVERSAL entry always applies — it is the floor, so an unrecognised company is still screened.
    """
    applies: list[str] = []
    suppressed: list[str] = []
    notes: list[str] = []

    for key in ("UNIVERSAL", *[m.value for m in models]):
        entry = config.get(key)
        if entry is None:
            continue
        for check in entry.get("applies", ()):
            if check not in applies:
                applies.append(check)
        for check in entry.get("suppress", ()):
            if check not in suppressed:
                suppressed.append(check)
        for note in entry.get("priority_notes", ()):
            if note not in notes:
                notes.append(note)

    return Playbook(
        models=tuple(models),
        applies=tuple(c for c in applies if c not in suppressed),
        suppressed=tuple(suppressed),
        priority_notes=tuple(notes),
    )
