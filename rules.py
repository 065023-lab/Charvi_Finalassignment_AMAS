"""Rule-based variance analysis for BudgetLens.

The arithmetic decides every number, every flag and the top 3 outliers.
The AI only writes commentary about results it is given, and answers questions.
"""
from dataclasses import dataclass, field
from statistics import median


@dataclass
class Settings:
    pct_threshold: float = 10.0      # a variance is material only if it is at least this % of budget...
    amount_threshold: float = 50000  # ...and at least this many rupees
    top_n: int = 3


@dataclass
class LineResult:
    department: str
    line_item: str
    type: str
    budget: float
    actual: float
    owner: str = ""
    notes: str = ""
    variance: float = 0.0            # actual - budget
    variance_pct: float = None       # None when budget is zero
    impact: float = 0.0              # + favourable to profit, - adverse
    direction: str = "On budget"
    material: bool = False
    top_rank: int = 0
    persistent: bool = False
    flags: list = field(default_factory=list)

    @property
    def key(self):
        return f"{self.department} · {self.line_item}"


def _direction(type_, variance):
    if abs(variance) < 0.5:
        return "On budget", 0.0
    impact = variance if type_ == "Revenue" else -variance
    return ("Favourable" if impact > 0 else "Adverse"), impact


def analyse_line(row: dict, s: Settings) -> LineResult:
    r = LineResult(department=row["department"], line_item=row["line_item"], type=row["type"],
                   budget=float(row["budget"]), actual=float(row["actual"]), owner=row.get("owner", ""),
                   notes=row.get("notes", ""))
    r.variance = r.actual - r.budget
    r.variance_pct = (r.variance / abs(r.budget) * 100) if r.budget else None
    r.direction, r.impact = _direction(r.type, r.variance)
    if r.budget == 0 and r.actual != 0:
        r.flags.append("Not in the budget at all.")
        r.material = abs(r.actual) >= s.amount_threshold
    else:
        r.material = abs(r.variance) >= s.amount_threshold and r.variance_pct is not None and abs(r.variance_pct) >= s.pct_threshold
    if r.actual < 0:
        r.flags.append("Negative actual: check the sign in the source data.")
    if not r.material and r.budget and abs(r.variance) >= 10 * s.amount_threshold:
        r.flags.append(f"Large in rupees (Rs {abs(r.variance):,.0f}) though only {r.variance_pct:+.1f}% of budget; "
                       "consider reporting it anyway.")
    near_pct = r.variance_pct is not None and abs(abs(r.variance_pct) - s.pct_threshold) <= 0.5
    if near_pct and abs(r.variance) >= s.amount_threshold:
        r.flags.append(f"Borderline: within 0.5 points of the {s.pct_threshold:g}% materiality line.")
    return r


def analyse_month(rows: list, s: Settings = Settings(), earlier: dict = None):
    """rows: clean line dicts for one month. earlier: {month: [rows]} for the persistence check.

    Returns (results, summary)."""
    results = [analyse_line(r, s) for r in rows]

    # Unusual swings: robust z-score of variance % (median and MAD), for lines that are not already material
    pcts = [r.variance_pct for r in results if r.variance_pct is not None]
    if len(pcts) >= 5:
        med = median(pcts)
        mad = median(abs(p - med) for p in pcts) or 1e-9
        for r in results:
            if r.variance_pct is not None and not r.material:
                z = 0.6745 * (r.variance_pct - med) / mad
                if abs(z) > 3.5 and abs(r.variance_pct) >= s.pct_threshold:
                    r.flags.append(f"Unusual swing ({r.variance_pct:+.0f}%) but below Rs {s.amount_threshold:,.0f}; "
                                   "worth a quick look, not a report item.")

    # Persistent adverse variances: material and adverse in each of the two previous months too
    if earlier:
        months = sorted(earlier)[-2:]
        if len(months) == 2:
            past = []
            for m in months:
                prev = {(x["department"], x["line_item"]): analyse_line(x, s) for x in earlier[m]}
                past.append(prev)
            for r in results:
                k = (r.department, r.line_item)
                if r.material and r.direction == "Adverse" and all(
                        k in p and p[k].material and p[k].direction == "Adverse" for p in past):
                    r.persistent = True
                    r.flags.append("Adverse and material 3 months running: likely a structural issue, not timing.")

    # Top N outliers: largest rupee variance among material lines
    material = sorted([r for r in results if r.material], key=lambda r: -abs(r.variance if r.budget else r.actual))
    for i, r in enumerate(material[:s.top_n], start=1):
        r.top_rank = i
    return results, summarize(results)


def summarize(results):
    rev_b = sum(r.budget for r in results if r.type == "Revenue")
    rev_a = sum(r.actual for r in results if r.type == "Revenue")
    cost_b = sum(r.budget for r in results if r.type == "Cost")
    cost_a = sum(r.actual for r in results if r.type == "Cost")
    op_b, op_a = rev_b - cost_b, rev_a - cost_a
    return {"lines": len(results), "material": sum(r.material for r in results),
            "adverse_material": sum(r.material and r.direction == "Adverse" for r in results),
            "revenue_budget": rev_b, "revenue_actual": rev_a, "cost_budget": cost_b, "cost_actual": cost_a,
            "profit_budget": op_b, "profit_actual": op_a, "profit_variance": op_a - op_b,
            "profit_variance_pct": ((op_a - op_b) / abs(op_b) * 100) if op_b else None}
