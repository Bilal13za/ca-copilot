"""Accounting Workbench: deterministic spreadsheet analysis.

Everything here is plain, tested Python — the AI may *explain* findings but
never computes them. All functions are pure (DataFrame in, findings out) so
they are easy to unit-test.

Conventions:
- Every finding carries the ORIGINAL row reference (1-based, as in Excel/CSV
  including the header row) so the user can locate it in the source file.
- Ambiguous matches are reported, never silently merged or discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None


def _need_pandas():
    if pd is None:
        raise RuntimeError("The 'pandas' package is required for the workbench.")


@dataclass
class Finding:
    kind: str                 # duplicate | unmatched | amount_difference | blank_required | ...
    severity: str             # error | warning | info
    message: str
    row_ref: int | None = None
    column: str | None = None
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "severity": self.severity, "message": self.message,
                "row_ref": self.row_ref, "column": self.column, "details": self.details}


# ---------------------------------------------------------------- Loading

def load_table(path: str | Path, *, sheet: str | int | None = 0) -> "pd.DataFrame":
    """Load a CSV or XLSX file. Adds _src_row = original 1-based row number."""
    _need_pandas()
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet, dtype=str, engine="openpyxl",
                           keep_default_na=False)
    else:
        raise ValueError(f"Unsupported workbench file type '{ext}'. Use CSV or XLSX.")
    df = df.copy()
    df["_src_row"] = range(2, len(df) + 2)  # header is row 1
    return df


def sheet_names(path: str | Path) -> list[str]:
    _need_pandas()
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def to_number(series: "pd.Series") -> "pd.Series":
    """Parse a column to numbers; unparseable -> NaN (flagged separately)."""
    _need_pandas()
    cleaned = series.astype(str).str.strip().str.replace(",", "", regex=False)
    cleaned = cleaned.replace({"": None, "-": None, "nan": None, "None": None})
    return pd.to_numeric(cleaned, errors="coerce")


# ---------------------------------------------------------------- A. Inspection

def inspect_table(df: "pd.DataFrame", name: str = "dataset") -> dict[str, Any]:
    """Profile a table: shape, columns, dtypes, blanks, numeric totals."""
    _need_pandas()
    cols = []
    for col in df.columns:
        if col == "_src_row":
            continue
        s = df[col]
        blank = int((s.astype(str).str.strip() == "").sum())
        nums = to_number(s)
        numeric = int(nums.notna().sum())
        col_info: dict[str, Any] = {
            "name": col, "non_blank": int(len(s) - blank), "blank": blank,
            "numeric_values": numeric,
        }
        if numeric:
            col_info["total"] = round(float(nums.sum()), 2)
            col_info["min"] = round(float(nums.min()), 2)
            col_info["max"] = round(float(nums.max()), 2)
        cols.append(col_info)
    return {"name": name, "rows": len(df), "columns": cols}


# ---------------------------------------------------------------- B. Duplicate detection

def find_duplicates(df: "pd.DataFrame", columns: list[str]) -> list[Finding]:
    """Find rows sharing the same values across `columns`. Blank keys are ignored
    (reported separately by validation) so empty cells don't false-positive."""
    _need_pandas()
    for c in columns:
        if c not in df.columns:
            raise ValueError(f"Column '{c}' not in dataset.")
    key = df[columns].astype(str).apply(lambda r: "‖".join(v.strip() for v in r), axis=1)
    nonblank = key.str.strip("‖ ").astype(bool)
    dup_mask = key.duplicated(keep=False) & nonblank
    findings: list[Finding] = []
    for key_val, group in df[dup_mask].groupby(key[dup_mask]):
        rows = sorted(int(r) for r in group["_src_row"])
        findings.append(Finding(
            kind="duplicate", severity="error",
            message=(f"Duplicate {', '.join(columns)} '{key_val}': "
                     f"{len(group)} rows (source rows {rows})."),
            row_ref=rows[0], column=", ".join(columns),
            details={"key": key_val, "count": len(group), "rows": rows,
                     "records": group.drop(columns=["_src_row"]).to_dict("records")},
        ))
    return findings


# ---------------------------------------------------------------- C. Reconciliation

@dataclass
class ColumnMap:
    id: str
    amount: str
    date: str | None = None
    description: str | None = None


def _norm_id(v: Any) -> str:
    return str(v).strip()


def reconcile(df_a: "pd.DataFrame", df_b: "pd.DataFrame",
              map_a: ColumnMap, map_b: ColumnMap,
              *, amount_tolerance: float = 0.01,
              date_tolerance_days: int = 0,
              label_a: str = "A", label_b: str = "B") -> dict[str, Any]:
    """Reconcile two datasets on mapped ID columns.

    Returns a dict with: matched, amount_differences, unmatched_a, unmatched_b,
    duplicates_within_a, duplicates_within_b, ambiguous, suggestions.
    Ambiguous = an ID occurring more than once on either side: listed for human
    review, never auto-matched.
    """
    _need_pandas()
    for m, df, label in ((map_a, df_a, label_a), (map_b, df_b, label_b)):
        for col in (m.id, m.amount):
            if col not in df.columns:
                raise ValueError(f"{label}: column '{col}' not found.")

    def prep(df: "pd.DataFrame", m: ColumnMap, label: str):
        recs = []
        for _, r in df.iterrows():
            raw_id = _norm_id(r[m.id])
            amt = to_number(pd.Series([r[m.amount]])).iloc[0]
            recs.append({"row_ref": int(r["_src_row"]), "id": raw_id,
                         "amount": None if pd.isna(amt) else float(amt),
                         "date": str(r[m.date]).strip() if m.date and m.date in df.columns else "",
                         "desc": str(r[m.description]).strip() if m.description and m.description in df.columns else "",
                         "label": label, "record": {c: r[c] for c in df.columns if c != "_src_row"}})
        return recs

    recs_a, recs_b = prep(df_a, map_a, label_a), prep(df_b, map_b, label_b)

    blank_a = [r for r in recs_a if not r["id"]]
    blank_b = [r for r in recs_b if not r["id"]]

    def index_unique(recs):
        by_id: dict[str, list[dict]] = {}
        for r in recs:
            if r["id"]:
                by_id.setdefault(r["id"], []).append(r)
        return by_id

    ia, ib = index_unique([r for r in recs_a if r not in blank_a]), index_unique([r for r in recs_b if r not in blank_b])

    duplicates_a = {k: v for k, v in ia.items() if len(v) > 1}
    duplicates_b = {k: v for k, v in ib.items() if len(v) > 1}
    ambiguous_ids = set(duplicates_a) | set(duplicates_b)

    matched, amount_diffs, unmatched_a, unmatched_b = [], [], [], []
    for _id, ra_list in ia.items():
        rb_list = ib.get(_id)
        if _id in ambiguous_ids:
            continue  # reported under ambiguous; never auto-matched
        if not rb_list:
            unmatched_a.extend(ra_list)
            continue
        ra, rb = ra_list[0], rb_list[0]
        if ra["amount"] is None or rb["amount"] is None:
            amount_diffs.append({"id": _id, "note": "amount not parseable on one side",
                                 "a": ra, "b": rb})
        elif abs(ra["amount"] - rb["amount"]) <= amount_tolerance:
            matched.append({"id": _id, "a": ra, "b": rb})
        else:
            amount_diffs.append({"id": _id, "a": ra, "b": rb,
                                 "difference": round(ra["amount"] - rb["amount"], 2)})
    for _id, rb_list in ib.items():
        if _id in ambiguous_ids or _id in ia:
            continue
        unmatched_b.extend(rb_list)

    ambiguous = []
    for _id in sorted(ambiguous_ids):
        ambiguous.append({"id": _id,
                          "side_a_rows": [r["row_ref"] for r in duplicates_a.get(_id, [])],
                          "side_b_rows": [r["row_ref"] for r in duplicates_b.get(_id, [])],
                          "note": "ID appears more than once — review manually; not auto-matched."})

    # Suggestions for the unmatched: same amount (±tolerance) and same date, different ID.
    suggestions = []
    pool_b = [r for _id, rs in ib.items() if _id not in ambiguous_ids for r in rs if _id not in ia]
    for ra in unmatched_a:
        if ra["amount"] is None:
            continue
        cands = [rb for rb in pool_b
                 if rb["amount"] is not None
                 and abs(rb["amount"] - ra["amount"]) <= amount_tolerance
                 and (not date_tolerance_days or ra["date"] == rb["date"] or True)]
        # date check kept simple: exact date equality when both present
        cands = [rb for rb in cands
                 if not (ra["date"] and rb["date"]) or ra["date"] == rb["date"]]
        if cands:
            suggestions.append({"a_row": ra["row_ref"], "a_id": ra["id"],
                                "candidates": [{"b_row": c["row_ref"], "b_id": c["id"],
                                                "amount": c["amount"]} for c in cands[:5]],
                                "note": "Possible match — human review required."})

    return {
        "matched": matched,
        "amount_differences": amount_diffs,
        "unmatched_a": unmatched_a,
        "unmatched_b": unmatched_b,
        "blank_ids_a": blank_a,
        "blank_ids_b": blank_b,
        "duplicates_within_a": [{"id": k, "rows": [r["row_ref"] for r in v]} for k, v in duplicates_a.items()],
        "duplicates_within_b": [{"id": k, "rows": [r["row_ref"] for r in v]} for k, v in duplicates_b.items()],
        "ambiguous": ambiguous,
        "suggestions": suggestions,
        "summary": {
            "total_a": len(recs_a), "total_b": len(recs_b),
            "matched": len(matched),
            "amount_differences": len(amount_diffs),
            "unmatched_a": len(unmatched_a), "unmatched_b": len(unmatched_b),
            "ambiguous_ids": len(ambiguous),
        },
    }


# ---------------------------------------------------------------- D. Validation

@dataclass
class ValidationRules:
    required_columns: list[str] = field(default_factory=list)
    date_columns: list[str] = field(default_factory=list)
    amount_columns: list[str] = field(default_factory=list)
    # arithmetic: each entry {"columns": [...], "equals": column-or-number, "label": str}
    total_checks: list[dict] = field(default_factory=list)
    # sign rule: amounts in `column` must be >= 0 (or <= 0)
    non_negative_columns: list[str] = field(default_factory=list)
    non_positive_columns: list[str] = field(default_factory=list)


def _parse_date(v: str):
    v = str(v).strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
                "%d-%b-%Y", "%d %b %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(v, dayfirst=True).date()
    except Exception:
        return None


def validate_table(df: "pd.DataFrame", rules: ValidationRules,
                   name: str = "dataset") -> list[Finding]:
    """Row-level checks. Mathematical errors are 'error'; judgement calls are
    'warning'/'info' and labelled for human review."""
    _need_pandas()
    findings: list[Finding] = []

    for col in rules.required_columns:
        if col not in df.columns:
            findings.append(Finding("missing_column", "error",
                                    f"Required column '{col}' is missing from {name}.",
                                    column=col))
            continue
        blanks = df[df[col].astype(str).str.strip() == ""]
        for _, r in blanks.iterrows():
            findings.append(Finding("blank_required", "error",
                                    f"Blank required field '{col}'.",
                                    row_ref=int(r["_src_row"]), column=col))

    for col in rules.date_columns:
        if col not in df.columns:
            continue
        for _, r in df.iterrows():
            v = str(r[col]).strip()
            if not v:
                continue
            if _parse_date(v) is None:
                findings.append(Finding("invalid_date", "error",
                                        f"Unrecognised date '{v}' in '{col}'.",
                                        row_ref=int(r["_src_row"]), column=col))

    for col in rules.amount_columns:
        if col not in df.columns:
            continue
        nums = to_number(df[col])
        bad = df[nums.isna() & (df[col].astype(str).str.strip() != "")]
        for _, r in bad.iterrows():
            findings.append(Finding("invalid_amount", "error",
                                    f"Amount '{r[col]}' in '{col}' is not a number.",
                                    row_ref=int(r["_src_row"]), column=col))

    for col in rules.non_negative_columns:
        if col not in df.columns:
            continue
        nums = to_number(df[col])
        for idx in nums[nums < 0].index:
            r = df.loc[idx]
            findings.append(Finding("inconsistent_sign", "warning",
                                    f"Negative value {r[col]} in '{col}' which is expected "
                                    "to be non-negative — verify whether a credit/refund "
                                    "is intended (human review).",
                                    row_ref=int(r["_src_row"]), column=col))
    for col in rules.non_positive_columns:
        if col not in df.columns:
            continue
        nums = to_number(df[col])
        for idx in nums[nums > 0].index:
            r = df.loc[idx]
            findings.append(Finding("inconsistent_sign", "warning",
                                    f"Positive value {r[col]} in '{col}' which is expected "
                                    "to be non-positive — human review.",
                                    row_ref=int(r["_src_row"]), column=col))

    # Arithmetic total checks — mathematical errors, severity error.
    for check in rules.total_checks:
        cols = check.get("columns", [])
        target = check.get("equals")
        label = check.get("label", "+".join(cols))
        if any(c not in df.columns for c in cols):
            continue
        # simpler: sum numeric columns row-wise
        row_sum = sum(to_number(df[c]).fillna(0) for c in cols)
        if isinstance(target, str) and target in df.columns:
            expected = to_number(df[target])
            bad = (row_sum - expected).abs() > 0.01
            bad = bad & row_sum.notna()
            for idx in df[bad].index:
                r = df.loc[idx]
                findings.append(Finding(
                    "arithmetic_mismatch", "error",
                    f"{label}: {' + '.join(cols)} = {row_sum.loc[idx]:.2f} but "
                    f"'{target}' = {r[target]}.",
                    row_ref=int(r["_src_row"]), column=target,
                    details={"computed": float(row_sum.loc[idx])}))
        elif isinstance(target, (int, float)):
            bad = (row_sum - float(target)).abs() > 0.01
            for idx in df[bad].index:
                r = df.loc[idx]
                findings.append(Finding(
                    "arithmetic_mismatch", "error",
                    f"{label}: row total {row_sum.loc[idx]:.2f} != expected {target}.",
                    row_ref=int(r["_src_row"]),
                    details={"computed": float(row_sum.loc[idx])}))

    # Suspicious patterns — judgement calls, severity info/warning.
    for col in rules.amount_columns:
        if col not in df.columns:
            continue
        nums = to_number(df[col]).dropna()
        if len(nums) >= 5:
            med = nums.abs().median()
            # Unusually large vs the typical magnitude: 10x the median.
            big = nums[nums.abs() > max(10 * med, 1)]
            for idx in big.index:
                r = df.loc[idx]
                findings.append(Finding(
                    "outlier", "info",
                    f"Amount {r[col]} in '{col}' is unusually large vs the rest of "
                    "the column — verify it is genuine (human review).",
                    row_ref=int(r["_src_row"]), column=col))
        round_mask = (nums != 0) & (nums.abs() % 1000 == 0)
        if int(round_mask.sum()) >= 3 and int(round_mask.sum()) / max(len(nums), 1) > 0.5:
            findings.append(Finding(
                "suspicious_round", "info",
                f"Over half the values in '{col}' are exact thousands — check for "
                "estimates/placeholders (human review).", column=col))
    return findings


# ---------------------------------------------------------------- E. Reports

def findings_to_frame(findings: list[Finding]) -> "pd.DataFrame":
    _need_pandas()
    return pd.DataFrame([f.as_dict() for f in findings])


def export_report(df_or_findings, path: str | Path, *, fmt: str = "xlsx",
                  summary: dict | None = None) -> Path:
    """Write findings (and optional summary sheet) to CSV or XLSX. Returns path."""
    _need_pandas()
    path = Path(path)
    if isinstance(df_or_findings, list):
        df = findings_to_frame(df_or_findings)
    else:
        df = df_or_findings
    if df.empty:
        df = pd.DataFrame([{"note": "No findings — all checks passed."}])
    # Flatten dict details for spreadsheet readability.
    if "details" in df.columns:
        df = df.copy()
        df["details"] = df["details"].apply(
            lambda d: "" if not d else "; ".join(f"{k}={v}" for k, v in d.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "xlsx":
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Findings", index=False)
            if summary:
                pd.DataFrame([{"item": k, "value": v} for k, v in summary.items()]).to_excel(
                    writer, sheet_name="Summary", index=False)
    else:
        raise ValueError("fmt must be 'csv' or 'xlsx'")
    return path
