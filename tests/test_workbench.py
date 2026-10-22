"""Tests for the deterministic accounting workbench.

Expected results below were computed by hand from the sample_data files —
reconciliation "matches" the independently calculated expectations.
"""

import pytest

from ca_copilot import workbench as wb
from ca_copilot.workbench import ColumnMap, Finding, ValidationRules


@pytest.fixture()
def bank(sample_data):
    return wb.load_table(sample_data / "bank_statement.csv")


@pytest.fixture()
def book(sample_data):
    return wb.load_table(sample_data / "cash_book.csv")


def test_load_table_row_refs(bank):
    assert len(bank) == 10
    # header is row 1 -> first data row is source row 2
    assert list(bank["_src_row"][:3]) == [2, 3, 4]


def test_inspect_table(bank):
    info = wb.inspect_table(bank, "bank")
    assert info["rows"] == 10
    amounts = next(c for c in info["columns"] if c["name"] == "Amount")
    assert amounts["total"] == pytest.approx(50000 + 12500 + 200000 + 18750 + 1500
                                             + 75000 + 30000 + 9000 + 45000 + 12000)
    assert amounts["blank"] == 0


def test_reconciliation_expected_results(bank, book):
    result = wb.reconcile(
        bank, book,
        ColumnMap(id="Ref", amount="Amount", date="Date", description="Description"),
        ColumnMap(id="Ref", amount="Amount", date="Date", description="Narration"),
        amount_tolerance=0.01, label_a="Bank", label_b="Book")
    s = result["summary"]
    # Hand-computed expectations from the sample files:
    assert s["matched"] == 6            # TXN-001..006 exact
    assert s["amount_differences"] == 1  # TXN-009: 45000 vs 45500
    assert s["unmatched_a"] == 1        # TXN-007 only in bank
    assert s["unmatched_b"] == 1        # TXN-010 only in book
    assert s["ambiguous_ids"] == 1      # TXN-008 duplicated in book
    assert len(result["blank_ids_a"]) == 1  # missing ref row in bank
    assert result["ambiguous"][0]["id"] == "TXN-008"
    diff = result["amount_differences"][0]
    assert diff["id"] == "TXN-009"
    assert diff["difference"] == pytest.approx(-500.0)


def test_reconciliation_never_silently_merges(bank, book):
    result = wb.reconcile(
        bank, book,
        ColumnMap(id="Ref", amount="Amount"),
        ColumnMap(id="Ref", amount="Amount"),
        label_a="Bank", label_b="Book")
    matched_ids = {m["id"] for m in result["matched"]}
    assert "TXN-008" not in matched_ids  # ambiguous -> kept out of matched
    assert result["duplicates_within_b"] == [{"id": "TXN-008", "rows": [9, 10]}]


def test_duplicate_invoices(sample_data):
    df = wb.load_table(sample_data / "duplicate_invoices.csv")
    findings = wb.find_duplicates(df, ["InvoiceNo"])
    keys = sorted(f.details["key"] for f in findings)
    assert keys == ["INV-1002", "INV-1004"]
    inv1002 = next(f for f in findings if f.details["key"] == "INV-1002")
    assert inv1002.details["rows"] == [3, 5]  # original CSV row numbers
    assert inv1002.severity == "error"


def test_duplicate_ignores_blank_keys(sample_data):
    df = wb.load_table(sample_data / "bank_statement.csv")
    findings = wb.find_duplicates(df, ["Ref"])
    assert findings == []  # the single blank ref must not false-positive


def test_validation_missing_values(sample_data):
    df = wb.load_table(sample_data / "missing_values.csv")
    rules = ValidationRules(
        required_columns=["TxnID", "Date", "Description"],
        date_columns=["Date"],
        amount_columns=["Debit", "Credit"],
        non_negative_columns=["Debit", "Credit"],
    )
    findings = wb.validate_table(df, rules)
    by_kind = {}
    for f in findings:
        by_kind.setdefault(f.kind, []).append(f)

    assert any(f.row_ref == 3 for f in by_kind["blank_required"])      # T2 blank date
    assert any("32/13/2026" in f.message for f in by_kind["invalid_date"])
    assert any(f.row_ref == 6 for f in by_kind["invalid_amount"])      # T5 'abc'
    negs = by_kind["inconsistent_sign"]
    assert negs and all(f.severity == "warning" for f in negs)        # T6 negative debit
    assert any(f.row_ref == 8 for f in by_kind["outlier"])             # T7 5,000,000
    assert "suspicious_round" in by_kind                               # exact thousands
    # judgement calls must not be severity 'error'
    for f in by_kind["outlier"] + by_kind["suspicious_round"]:
        assert f.severity in ("info", "warning")


def test_arithmetic_total_check(sample_data):
    import pandas as pd
    df = pd.DataFrame({
        "A": ["10", "20", "30"],
        "B": ["5", "5", "5"],
        "Total": ["15", "25", "99"],
        "_src_row": [2, 3, 4],
    })
    rules = ValidationRules(total_checks=[{"columns": ["A", "B"], "equals": "Total",
                                           "label": "A+B=Total"}])
    findings = wb.validate_table(df, rules)
    assert len(findings) == 1
    assert findings[0].kind == "arithmetic_mismatch"
    assert findings[0].row_ref == 4


def test_export_csv_and_xlsx_roundtrip(bank, tmp_path):
    findings = [Finding("duplicate", "error", "test finding", row_ref=3, column="Ref")]
    csv_path = wb.export_report(findings, tmp_path / "rep.csv", fmt="csv")
    xlsx_path = wb.export_report(findings, tmp_path / "rep.xlsx", fmt="xlsx",
                                 summary={"matched": 6})
    import pandas as pd
    back_csv = pd.read_csv(csv_path)
    assert "test finding" in back_csv["message"].iloc[0]
    back_xlsx = pd.read_excel(xlsx_path, sheet_name="Findings")
    assert "test finding" in back_xlsx["message"].iloc[0]
    summary = pd.read_excel(xlsx_path, sheet_name="Summary")
    assert int(summary.loc[summary["item"] == "matched", "value"].iloc[0]) == 6


def test_sheet_names(tmp_path):
    import openpyxl
    p = tmp_path / "multi.xlsx"
    wb_ = openpyxl.Workbook()
    wb_.active.title = "One"
    wb_.create_sheet("Two")
    wb_.save(p)
    assert wb.sheet_names(p) == ["One", "Two"]
