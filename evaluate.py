"""Compare BudgetLens's materiality flags with past confirmed issues, and with two simple rules of thumb."""
import pandas as pd

from rules import Settings, analyse_line
from validation import clean_file


def evaluate(df: pd.DataFrame, s: Settings):
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "real_issue" not in df.columns:
        raise ValueError("The file needs a real_issue column (1 if the variance turned out to be a genuine problem, else 0).")
    months, problems, fatal = clean_file(df)
    if fatal:
        raise ValueError(fatal)
    truth = {(str(r["month"])[:7], str(r["department"]).strip(), str(r["line_item"]).strip()): int(r["real_issue"])
             for r in df.to_dict("records")}
    recs = []
    for month, rows in months.items():
        for row in rows:
            r = analyse_line(row, s)
            pct = abs(r.variance_pct) if r.variance_pct is not None else 999
            recs.append({"month": month, "line": r.key, "budget": r.budget, "variance": r.variance,
                         "budgetlens": r.material, "pct_rule": pct >= s.pct_threshold,
                         "amount_rule": abs(r.variance) >= s.amount_threshold,
                         "issue": bool(truth.get((month, row["department"], row["line_item"]), 0))})
    d = pd.DataFrame(recs)
    if d.empty:
        raise ValueError("No rows could be compared.")
    out = {}
    for k, name in (("budgetlens", "BudgetLens (both % and Rs)"), ("pct_rule", f"Rule of thumb: over {s.pct_threshold:g}%"),
                    ("amount_rule", f"Rule of thumb: over Rs {s.amount_threshold:,.0f}")):
        f = d[k]
        out[name] = {"flagged": int(f.sum()), "caught": int((f & d.issue).sum()), "false_alarms": int((f & ~d.issue).sum())}
    return d, {"rows": len(d), "issues": int(d.issue.sum()), "methods": out, "skipped": len(problems)}
