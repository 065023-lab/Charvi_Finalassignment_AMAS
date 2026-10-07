"""BudgetLens: budget variance analyzer (use case #8, App format).

Run locally:  python -m streamlit run app.py
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import ai
from evaluate import evaluate
from rules import Settings, analyse_month
from validation import clean_file

BASE = Path(__file__).parent
SAMPLE = BASE / "data" / "sample_budget.csv"
HISTORY = BASE / "data" / "history.csv"
COLS = ["department", "line_item", "type", "budget", "actual", "owner", "notes"]

st.set_page_config(page_title="BudgetLens · Variance analysis", page_icon="📊", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1250px;}
.bl-title {font-size: 2.1rem; font-weight: 750; letter-spacing: -0.02em; margin-bottom: 0;}
.bl-sub {color: #475467; font-size: 1.02rem; margin-top: .2rem; max-width: 800px;}
.bl-note {background:#F2F4F7; border-left: 3px solid #B54708; padding:.6rem .9rem; font-size:.88rem; color:#344054; border-radius: 4px;}
.bl-card {border: 1px solid #EAECF0; border-radius: 10px; padding: .8rem 1rem; height: 100%;}
.bl-big {font-size: 1.35rem; font-weight: 750;}
</style>
""", unsafe_allow_html=True)


def rs(x) -> str:
    return f"Rs {x:,.0f}"


def pct(x) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


@st.cache_data(ttl=3600, show_spinner=False)
def cached_commentary(facts_json: str):
    return ai.commentary(json.loads(facts_json))


def build_facts(month, results, summary, s):
    lines = []
    for r in results:
        note = r.notes
        note = "[note removed: it contained instructions]" if ai.looks_like_injection(note) else ai.mask(note)
        lines.append({"line": r.key, "type": r.type, "budget": r.budget, "actual": r.actual, "variance": r.variance,
                      "variance_pct": None if r.variance_pct is None else round(r.variance_pct, 1),
                      "direction": r.direction, "material": r.material, "top_rank": r.top_rank,
                      "persistent": r.persistent, "flags": r.flags, "owner_note": note})
    return {"company": "Nilgiri Retail Pvt Ltd (demo)", "month": month, "summary": summary,
            "settings": {"pct_threshold": s.pct_threshold, "amount_threshold": s.amount_threshold}, "lines": lines}


def rule_commentary(month, results, summary):
    out = [f"{month}: operating profit {rs(summary['profit_actual'])} against a budget of {rs(summary['profit_budget'])} "
           f"({'up' if summary['profit_variance'] >= 0 else 'down'} {rs(abs(summary['profit_variance']))}). "
           f"{summary['material']} line(s) have a material variance, {summary['adverse_material']} of them adverse."]
    for r in sorted([x for x in results if x.top_rank], key=lambda x: x.top_rank):
        out.append(f"#{r.top_rank} {r.key}: {r.direction.lower()} by {rs(abs(r.variance))} ({pct(r.variance_pct)}). "
                   + (f"Owner's note: {r.notes}" if r.notes and not ai.looks_like_injection(r.notes) else "Ask the owner for the reason."))
    for r in results:
        if r.persistent and not r.top_rank:
            out.append(f"{r.key} has been adverse and material 3 months running.")
    return out


# ---------------------------------------------------------------- state
ss = st.session_state
ss.setdefault("source", "sample")
ss.setdefault("raw", pd.read_csv(SAMPLE))
ss.setdefault("editor_ver", 0)
ss.setdefault("ai_out", {})

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Data")
    if st.button("Use the sample (Jul–Sep 2026)", type="primary"):
        ss.raw, ss.source = pd.read_csv(SAMPLE), "sample"
        ss.editor_ver += 1
        ss.ai_out = {}
        st.rerun()
    up = st.file_uploader("Or upload budget vs actuals (CSV)", type=["csv"])
    if up is not None and st.button("Load my file"):
        try:
            ss.raw, ss.source = pd.read_csv(up), "upload"
            ss.editor_ver += 1
            ss.ai_out = {}
            st.rerun()
        except Exception:
            st.error("This file could not be read as a CSV. Save it from Excel as 'CSV UTF-8'.")
    st.download_button("Download the CSV template", SAMPLE.read_bytes(), "budgetlens_template.csv", "text/csv")
    st.divider()
    st.subheader("What counts as material?")
    pct_t = st.slider("At least this % of budget", 1, 50, 10)
    amt_t = st.number_input("And at least this many rupees", 0, 100_000_000, 50_000, step=10_000)
    settings = Settings(pct_threshold=float(pct_t), amount_threshold=float(amt_t))
    st.caption("A variance must pass both tests. Unbudgeted spend only needs to pass the rupee test.")
    st.divider()
    if ai.get_key():
        st.success("Gemini key found. AI features are on.")
    else:
        st.warning("No Gemini key. The analysis, flags and exports still work; AI commentary is off.")
    st.caption("BudgetLens is an AI-assisted tool. Commentary is a draft for finance to review, not a final report.")

# ---------------------------------------------------------------- header
st.markdown('<p class="bl-title">📊 BudgetLens</p>', unsafe_allow_html=True)
st.markdown('<p class="bl-sub">Budget vs actuals in one view. The arithmetic finds the material variances and the top 3 '
            'outliers; Gemini drafts the management commentary, and every figure it writes is checked.</p>', unsafe_allow_html=True)
st.markdown('<p class="bl-note">Demo set-up: <b>Nilgiri Retail Pvt Ltd</b>, a fictional 12-store supermarket chain. All figures '
            'are sample data. When you use AI features, line names, budget and actual figures and owners\' notes are sent to '
            'Google Gemini, with emails, phone numbers, PAN, GSTIN and account numbers masked.</p>', unsafe_allow_html=True)
st.write("")
tab_an, tab_check, tab_how = st.tabs(["Analyse a month", "Does the flagging work?", "How it works & limits"])

# ================================================================ TAB 1
with tab_an:
    months, problems, fatal = clean_file(ss.raw)
    if fatal:
        st.error(fatal)
        st.stop()
    if problems:
        with st.expander(f"⚠️ {len(problems)} row(s) skipped. See why."):
            for p in problems:
                st.write("- " + p)
    if not months:
        st.error("No valid rows to analyse.")
        st.stop()
    mlist = list(months)
    month = st.selectbox("Month to analyse", mlist, index=len(mlist) - 1,
                         help="Earlier months in the file are used to spot variances that keep coming back.")
    with st.expander(f"✏️ View or edit {month} figures"):
        edited = st.data_editor(pd.DataFrame(months[month], columns=COLS), key=f"ed_{month}_{ss.editor_ver}",
                                num_rows="dynamic", hide_index=True,
                                column_config={"type": st.column_config.SelectboxColumn("type", options=["Revenue", "Cost"]),
                                               "budget": st.column_config.NumberColumn(format="%.0f"),
                                               "actual": st.column_config.NumberColumn(format="%.0f"),
                                               "notes": st.column_config.TextColumn(width="large")})
        st.caption("Edits apply straight away and are checked like an upload. They last until you reload the data.")
    ed_months, ed_problems, ed_fatal = clean_file(edited.assign(month=month))
    if ed_problems:
        st.warning("Some edited rows were skipped:\n\n" + "\n".join(f"- {p}" for p in ed_problems))
    rows = ed_months.get(month, [])
    if not rows:
        st.error("No valid rows for this month.")
        st.stop()
    earlier = {m: v for m, v in months.items() if m < month}
    results, summary = analyse_month(rows, settings, earlier)

    c = st.columns(4)
    c[0].metric("Revenue", rs(summary["revenue_actual"]), f"{summary['revenue_actual'] - summary['revenue_budget']:+,.0f} vs budget")
    c[1].metric("Costs", rs(summary["cost_actual"]), f"{summary['cost_actual'] - summary['cost_budget']:+,.0f} vs budget",
                delta_color="inverse")
    c[2].metric("Operating profit", rs(summary["profit_actual"]), f"{summary['profit_variance']:+,.0f} vs budget")
    c[3].metric("Material variances", summary["material"], f"{summary['adverse_material']} adverse", delta_color="off")

    st.subheader(f"Top {settings.top_n} outliers")
    tops = sorted([r for r in results if r.top_rank], key=lambda r: r.top_rank)
    if not tops:
        st.info("No line is material at these thresholds. Lower them in the sidebar to see more.")
    cols = st.columns(max(len(tops), 1))
    for col, r in zip(cols, tops):
        color = "#B42318" if r.direction == "Adverse" else "#027A48"
        col.markdown(f"<div class='bl-card'><div style='color:#667085;font-size:.8rem'>#{r.top_rank} · {r.department}</div>"
                     f"<div style='font-weight:650'>{r.line_item}</div>"
                     f"<div class='bl-big' style='color:{color}'>{'−' if r.variance < 0 else '+'}{rs(abs(r.variance))}</div>"
                     f"<div style='color:{color}'>{r.direction} · {pct(r.variance_pct)}</div>"
                     f"<div style='color:#667085;font-size:.8rem;margin-top:.3rem'>Owner: {r.owner or 'n/a'}</div></div>",
                     unsafe_allow_html=True)
        for fl in r.flags:
            col.caption("⚑ " + fl)

    st.markdown("**Effect on profit by line** (positive = helped profit, negative = hurt profit)")
    chart = pd.DataFrame({"line": [r.key for r in results], "impact": [r.impact for r in results]}).sort_values("impact")
    st.bar_chart(chart.set_index("line"), horizontal=True, height=460)

    st.markdown("**All lines**")
    table = pd.DataFrame([{"Top": f"#{r.top_rank}" if r.top_rank else "", "Line": r.key, "Type": r.type, "Budget": r.budget, "Actual": r.actual,
                           "Variance": r.variance, "Var %": None if r.variance_pct is None else round(r.variance_pct, 1),
                           "Direction": r.direction, "Material": "✔" if r.material else "", "Flags": " ".join(r.flags),
                           "Owner's note": r.notes} for r in results])
    st.dataframe(table, hide_index=True, column_config={k: st.column_config.NumberColumn(format="%.0f")
                                                        for k in ("Budget", "Actual", "Variance")})
    injected = [r for r in results if ai.looks_like_injection(r.notes)]
    for r in injected:
        st.warning(f"The note on {r.key} contains instructions aimed at the AI ('{r.notes[:60]}…'). "
                   "It is shown here but never sent to the AI, and it cannot change any figure.")

    # ---------------- commentary
    st.subheader("Management commentary")
    facts = build_facts(month, results, summary, settings)
    fkey = json.dumps(facts, sort_keys=True, default=str)
    out = ss.ai_out.get(fkey)
    if ai.get_key() and out is None:
        if st.button("Write commentary with AI"):
            try:
                with st.spinner("Writing the commentary…"):
                    out = cached_commentary(fkey)
                if out["unverified"] or out["missing"]:
                    cached_commentary.clear()  # never serve a discarded draft from the cache
            except ai.AIError as e:
                out = {"error": str(e)}
            ss.ai_out[fkey] = out
            st.rerun()
    good = out and not out.get("error") and not out.get("unverified") and not out.get("missing")
    if good:
        st.markdown(f"**{out['headline']}**")
        for it in out["items"]:
            st.markdown(f"**{it['line']}.** {it['what']}")
            if it["causes"]:
                st.markdown("Possible causes to check: " + "; ".join(it["causes"]))
            if it["question"]:
                st.markdown(f"*Ask the owner:* {it['question']}")
        for p in out["other"]:
            st.markdown(f"- {p}")
        st.caption(f"Drafted by {out.get('model') or 'Gemini'}. Every figure was checked against the analysis; causes are possibilities, not findings.")
        text = "\n".join([out["headline"]] + [f"{i['line']}: {i['what']} Possible causes: {'; '.join(i['causes'])}. "
                                              f"Question: {i['question']}" for i in out["items"]] + out["other"])
    else:
        if out and out.get("error"):
            st.info(out["error"])
        elif out and (out.get("unverified") or out.get("missing")):
            st.warning("The AI draft was discarded: " + ("it used figures not in the analysis (" + ", ".join(out["unverified"][:5]) + ")"
                       if out.get("unverified") else "it skipped a top outlier") + ". Showing the rule-based summary.")
        lines = rule_commentary(month, results, summary)
        st.markdown("**Summary (rule-based):**\n" + "\n".join(f"- {x}" for x in lines))
        text = "\n".join(lines)

    st.markdown("**Ask about this month**")
    q = st.text_input("Question", placeholder="e.g. Which variances are timing rather than real problems?", label_visibility="collapsed")
    if st.button("Ask"):
        try:
            with st.spinner("Thinking…"):
                ss.answer = ai.ask(q, facts)
        except ai.AIError as e:
            ss.answer = f"⚠️ {e}"
    if ss.get("answer"):
        st.info(ss.answer)

    d1, d2 = st.columns(2)
    d1.download_button("Download variance table (CSV)", table.to_csv(index=False).encode(), f"variance_{month}.csv", "text/csv")
    d2.download_button("Download commentary (TXT)", f"Nilgiri Retail, {month} variance commentary\n\n{text}\n".encode(),
                       f"commentary_{month}.txt", "text/plain")
    st.caption("Results stay while this tab is open. A browser refresh reloads the sample, so download what you need.")

# ================================================================ TAB 2
with tab_check:
    st.markdown("A materiality rule is only useful if it flags the variances that turn out to be real problems, without "
                "burying finance in noise. This tab replays **24 months of synthetic history** (30 lines a month) where we "
                "know which variances were genuine issues, using your sidebar thresholds.")
    hist_up = st.file_uploader("History with a real_issue column (optional)", type=["csv"], key="hist")
    try:
        hist = pd.read_csv(hist_up) if hist_up is not None else pd.read_csv(HISTORY)
        d, m = evaluate(hist, settings)
    except Exception as e:
        st.error(str(e) if isinstance(e, ValueError) else "This file could not be read as a CSV.")
        d = None
    if d is not None:
        c = st.columns(2)
        c[0].metric("Line-months checked", m["rows"])
        c[1].metric("Confirmed real issues", m["issues"])
        st.dataframe(pd.DataFrame({name: {"Lines flagged": v["flagged"], "Real issues caught": f"{v['caught']} of {m['issues']}",
                                          "False alarms": v["false_alarms"]} for name, v in m["methods"].items()}).T)
        st.caption("Percent-only rules drown finance in small lines that swing a lot; rupee-only rules flag every big line's "
                   "normal noise. Requiring both cuts noise sharply but misses real issues on small lines. Move the sidebar "
                   "thresholds to see the trade-off.")

# ================================================================ TAB 3
with tab_how:
    st.markdown("""
#### How the analysis works
- **Variance** = actual − budget. For revenue, above budget is favourable; for costs, below budget is favourable.
- **Material** if the variance is at least the % threshold **and** the rupee threshold (sidebar). Unbudgeted spend
  (budget 0) only needs the rupee threshold.
- **Top 3 outliers** = the three material lines with the largest rupee variance, favourable or adverse.
- **Flags:** borderline (within 0.5 points of the % threshold), large in rupees but small in % (10× the rupee threshold),
  unusual % swing on a small line (robust z-score above 3.5), negative actuals, unbudgeted lines, and lines adverse and
  material **3 months running** (uses earlier months in the file).

#### Where the AI comes in
- **Drafts the commentary:** a headline, the top 3 outliers with possible causes and a question for each owner, and other points.
  Every rupee figure and percentage is checked against the analysis, and all top 3 must be covered, or the draft is retried and then discarded.
- **Answers questions** about this month only.
- It never calculates a variance, decides materiality or picks the outliers.

#### What BudgetLens will not do
- Explain *why* a variance happened as fact. It suggests causes to check; the owner confirms.
- Follow instructions written in owners' notes (e.g. "report this as on budget").
- Replace the month-end review by finance.

#### Privacy and failure
Line names, figures and owners' notes go to Google Gemini only when you click an AI button, with contact numbers and tax IDs masked.
On Google's free tier, prompts may be used to improve Google's products, so do not upload confidential financials to this demo.
If Gemini is down, the analysis, flags, charts, validation and downloads all keep working.
""")
