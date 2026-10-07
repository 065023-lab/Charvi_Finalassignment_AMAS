"""Checks that run before anything is analysed or sent to the AI."""
import re

import pandas as pd

REQUIRED = ["month", "department", "line_item", "type", "budget", "actual"]
OPTIONAL = ["owner", "notes"]
TYPES = {"revenue": "Revenue", "income": "Revenue", "sales": "Revenue", "cost": "Cost", "expense": "Cost", "expenses": "Cost"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_ABS = 10_000_000_000  # Rs 1,000 crore per line


def _blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == ""


def _num(v):
    s = str(v).replace(",", "").replace("₹", "").replace("Rs", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]  # accounting negatives
    return float(s)


def clean_file(df: pd.DataFrame):
    """Returns ({month: [rows]}, problems, fatal). Bad rows are skipped and listed, never guessed."""
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return {}, [], "The file is missing these columns: " + ", ".join(missing) + ". Download the template."
    if df.empty:
        return {}, [], "The file has headers but no rows."
    if len(df) > 20000:
        return {}, [], "Upload 20,000 rows or fewer."
    months, problems, seen = {}, [], {}
    for i, raw in enumerate(df.to_dict("records"), start=2):
        errs = []
        month = "" if _blank(raw["month"]) else str(raw["month"]).strip()[:7]
        if not MONTH_RE.match(month):
            errs.append("month must look like 2026-09")
        dept = "" if _blank(raw["department"]) else str(raw["department"]).strip()
        item = "" if _blank(raw["line_item"]) else str(raw["line_item"]).strip()
        if not dept or not item:
            errs.append("department and line item are required")
        typ = TYPES.get(str(raw["type"]).strip().lower())
        if not typ:
            errs.append("type must be Revenue or Cost")
        vals = {}
        for k in ("budget", "actual"):
            if _blank(raw[k]):
                errs.append(f"{k} is missing")
                continue
            try:
                x = _num(raw[k])
                if abs(x) > MAX_ABS:
                    errs.append(f"{k} looks like a typo (over Rs 1,000 crore)")
                vals[k] = x
            except ValueError:
                errs.append(f"{k} must be a number")
        if "budget" in vals and vals["budget"] < 0:
            errs.append("budget cannot be negative")
        key = (month, dept.lower(), item.lower())
        if not errs and key in seen:
            errs.append(f"duplicate of line {seen[key]} (same month, department and line item)")
        if errs:
            problems.append(f"Line {i} ({item or 'no line item'}): " + "; ".join(errs))
            continue
        seen[key] = i
        months.setdefault(month, []).append({
            "department": dept, "line_item": item, "type": typ, "budget": vals["budget"], "actual": vals["actual"],
            "owner": "" if _blank(raw.get("owner")) else str(raw["owner"]).strip(),
            "notes": "" if _blank(raw.get("notes")) else str(raw["notes"]).strip()[:500]})
    return dict(sorted(months.items())), problems, ""
