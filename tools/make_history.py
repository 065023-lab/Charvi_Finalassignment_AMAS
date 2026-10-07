"""Generate data/history.csv: 24 months x 30 line items of SYNTHETIC budget vs actuals.

Each row has `real_issue` = 1 where something genuinely changed (a price rise, a lost customer, leakage),
as a finance team would have confirmed after investigating. Everything else is normal noise:
small lines swing a lot in percent, big lines swing a lot in rupees. BudgetLens never sees `real_issue`.
Run from the project folder:  python tools/make_history.py
"""
import random
from pathlib import Path

import pandas as pd

random.seed(21)
lines = []
for i in range(30):
    budget = round(10 ** random.uniform(4.5, 7.4), -3)   # Rs ~30,000 to ~2.5 crore
    typ = "Revenue" if i < 6 else "Cost"
    lines.append((f"Dept {i % 6 + 1}", f"Line {i + 1:02d}", typ, budget))
rows = []
for m in range(24):
    month = f"{2024 + (m + 6) // 12}-{(m + 6) % 12 + 1:02d}"
    for dept, item, typ, budget in lines:
        sd = 0.04 if budget > 1_000_000 else (0.08 if budget > 100_000 else 0.18)
        actual = budget * (1 + random.gauss(0, sd))
        issue = random.random() < 0.08
        if issue:
            shift = random.uniform(0.12, 0.5)
            sign = -1 if typ == "Revenue" else 1
            if random.random() < 0.25:
                sign = -sign
            actual = budget * (1 + sign * shift + random.gauss(0, sd / 2))
        rows.append(dict(month=month, department=dept, line_item=item, type=typ, budget=budget,
                         actual=round(actual, -2), owner="", notes="", real_issue=int(issue)))
out = Path(__file__).resolve().parents[1] / "data" / "history.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print("wrote", len(rows), "rows;", sum(r["real_issue"] for r in rows), "real issues")
