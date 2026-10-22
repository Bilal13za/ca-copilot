"""Pakistan tax framework — SAFEGUARDS ONLY in this release.

This module defines HOW a future tax calculation module must behave. It ships
no tax rates and performs no tax computations. Any future tax feature must:

1. Record the tax year and effective date for every calculation.
2. Cite an identifiable, versioned source for every material rule
   (stored in the tax_rule_sources table).
3. Separate legal rules (data) from calculations (code).
4. Show assumptions, formulas, and workings for every result.
5. Flag missing information and ambiguous cases instead of guessing.
6. Include test cases for known examples.
7. Require human review before any filing or client advice.

Until those conditions are met for a given tax year, the app must refuse to
present a number as a tax liability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db


@dataclass
class TaxRuleSource:
    tax_year: str
    title: str
    source_ref: str
    effective_date: str = ""
    notes: str = ""


def add_rule_source(source: TaxRuleSource, conn=None) -> int:
    own = conn is None
    conn = conn or db.get_db()
    try:
        with db.transaction(conn) as cur:
            cur.execute(
                """INSERT INTO tax_rule_sources(tax_year, title, source_ref, effective_date, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (source.tax_year, source.title, source.source_ref,
                 source.effective_date or None, source.notes or None))
            return cur.lastrowid
    finally:
        if own:
            conn.close()


def list_rule_sources(tax_year: str | None = None, conn=None) -> list[dict[str, Any]]:
    own = conn is None
    conn = conn or db.get_db()
    try:
        if tax_year:
            rows = conn.execute(
                "SELECT * FROM tax_rule_sources WHERE tax_year = ? ORDER BY added_at",
                (tax_year,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tax_rule_sources ORDER BY tax_year, added_at").fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


TAX_NOT_READY_MESSAGE = (
    "Tax computation is not available in this release. CA Copilot does not ship "
    "tax rates or claim any filing compliance. When a tax module is added, every "
    "rule will cite a versioned source with its tax year and effective date, and "
    "every result will show assumptions, workings, and require human review."
)


def compute_tax_liability(*args, **kwargs):
    """Placeholder that always refuses — see module docstring."""
    raise NotImplementedError(TAX_NOT_READY_MESSAGE)
