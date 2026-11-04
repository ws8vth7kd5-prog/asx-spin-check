"""ASX results tone & spin - Streamlit website.

Run locally:  .venv\\Scripts\\streamlit run app.py
Scores are compared against data/benchmark.csv (every release scored in the research),
so tone 9/10 means "more upbeat than ~90% of ASX results releases we've scored".
"""
import io
import os
import re

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import engine
import extract_headlines as xh

st.set_page_config(page_title="ASX Results Tone & Spin", page_icon="📄", layout="centered")

BLUE, ORANGE = "#2a78d6", "#eb6834"
METRIC_NAMES = {"revenue": "Revenue", "npat_stat": "Statutory NPAT", "npat_underlying": "Underlying NPAT"}



@st.cache_resource(show_spinner="Loading FinBERT (first run only)...")
def finbert():
    return engine.load_finbert()


@st.cache_data
def benchmark():
    return pd.read_csv("data/benchmark.csv"), engine.load_spin_model()


def to_10(value, population):
    """1-10 score = where `value` sits among past releases (5.5 = typical, 10 = highest)."""
    pop = pd.Series(population).dropna()
    return 1 + 9 * (pop < value).mean(), (pop < value).mean()


def fmt_pct(p):
    return "n/a" if p is None or pd.isna(p) else f"{p:+.1f}%"


def guess_ticker(text):
    m = re.search(r"\bASX\s*(?:code)?\s*:\s*([A-Z0-9]{3})\b", text)
    return m.group(1) if m else ""


# ---------------- page ----------------
st.title("ASX Results Tone & Spin")
st.write("Upload an ASX company's results announcement to see **how upbeat the language is** "
         "and **whether that tone matches the numbers**.")
st.caption("Analysis only - not financial advice.")

tab_pdf, tab_text = st.tabs(["Upload PDF", "Paste text"])
with tab_pdf:
    upload = st.file_uploader("Results announcement (PDF)", type="pdf")
    examples = sorted(os.listdir("announcements")) if os.path.isdir("announcements") else []
    example = st.selectbox("...or try one we've scored", [""] + examples) if examples else ""
with tab_text:
    pasted = st.text_area("Paste the announcement text", height=200)
ticker_in = st.text_input("ASX ticker (optional)", max_chars=4,
                          help="Used to compare with the company's own past releases.").strip().upper()

if not st.button("Analyse", type="primary"):
    st.stop()

# ---------------- read ----------------
if upload or example:
    data = upload.getvalue() if upload else open(os.path.join("announcements", example), "rb").read()
    with st.spinner("Reading the PDF..."):
        text = engine.pdf_text(io.BytesIO(data))
        ticker = ticker_in or (example.split("_")[0] if example else "") or guess_ticker(text)
        numbers, _ = xh.headlines(io.BytesIO(data), ticker)
elif pasted.strip():
    text = pasted
    ticker = ticker_in or guess_ticker(text)
    numbers, _ = xh.headlines_from_text(text, ticker)
else:
    st.warning("Upload a PDF or paste some text first.")
    st.stop()

sents = engine.to_sentences(text)[:engine.MAX_SENTENCES]
if len(sents) < 5:
    st.error("Couldn't find enough readable sentences. The PDF may be scanned images rather than text.")
    st.stop()

with st.spinner(f"Scoring {len(sents)} sentences with FinBERT..."):
    scored = engine.score_sentences(finbert(), sents)
tone = engine.summarise(scored)["tone_net"]

bench, model = benchmark()
tone10, tone_share = to_10(tone, bench["tone_net"])
profit_pct, basis = engine.profit_change(numbers)
if profit_pct is not None:
    spin, expected = engine.spin_of(tone, profit_pct, model)
    spin10, spin_share = to_10(spin, bench["spin_pooled"])

# ---------------- scores ----------------
c1, c2, c3 = st.columns(3)
c1.metric("Tone", f"{tone10:.1f} / 10", help="Where this release's tone sits among past ASX results releases.")
if profit_pct is not None:
    c2.metric("Spin", f"{spin10:.1f} / 10",
              help="How upbeat it sounds compared with releases reporting a similar profit change.")
    c3.metric(f"Profit change ({basis})", fmt_pct(profit_pct))
else:
    c2.metric("Spin", "n/a", help="Needs a profit figure, and none was found.")
    c3.metric("Profit change", "not found")

# ---------------- summary ----------------
st.subheader("Summary")
in_text = {"revenue": "revenue", "npat_stat": "statutory NPAT", "npat_underlying": "underlying NPAT"}
nums = [f"{in_text[m]} {fmt_pct(numbers[m]['pct'])}" for m in METRIC_NAMES if numbers.get(m)]
lines = [("Versus the same period last year: " + ", ".join(nums) + ".") if nums
         else "No headline revenue or profit figures were found automatically.",
         f"The language is more upbeat than {tone_share:.0%} of the {len(bench)} ASX results releases we've scored."]
if profit_pct is not None:
    side = "more" if spin > 0 else "less"
    lines.append(f"It sounds {side} positive than releases with similar profit growth usually do "
                 f"(spin higher than {spin_share:.0%} of past releases).")
else:
    lines.append("Spin can't be measured without a profit figure.")
if ticker and ticker in set(bench["ticker"]):
    own = bench.loc[bench["ticker"] == ticker, "tone_net"]
    lines.append(f"Compared with {ticker}'s own {len(own)} past releases, the tone is higher than {(own < tone).sum()} of them.")
for line in lines:
    st.write("- " + line)

# ---------------- numbers ----------------
st.subheader("Key numbers")
rows = []
for m, name in METRIC_NAMES.items():
    n = numbers.get(m)
    rows.append({"Measure": name, "Change vs last year": fmt_pct(n["pct"]) if n else "not found",
                 "Confidence": n["confidence"] if n else "", "Page": int(n["page"]) if n else None,
                 "Found in": n["text"] if n else ""})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
             column_config={"Found in": st.column_config.TextColumn(width="large")})
st.caption("Found automatically. High = from the Appendix 4E/4D or a table we could cross-check; "
           "low = from a sentence with no $ figure beside it. Always check against the document.")

# ---------------- red flags ----------------
st.subheader("Red flags")
flags = 0
u, s = numbers.get("npat_underlying"), numbers.get("npat_stat")
if u and s and u["pct"] - s["pct"] > 15:
    st.warning(f"**Underlying profit ({fmt_pct(u['pct'])}) is much better than statutory profit ({fmt_pct(s['pct'])}).** "
               "Check what was excluded from 'underlying' and whether it's really one-off.")
    flags += 1
if profit_pct is not None and profit_pct < 0 and tone_share > 0.7:
    st.warning(f"**Profit fell ({fmt_pct(profit_pct)}) but the tone is more upbeat than {tone_share:.0%} of releases.**")
    flags += 1
if not flags:
    st.write("No number-based red flags.")
st.write("**Most upbeat sentences** - the ones doing the most 'selling':")
for _, r in scored.sort_values("net", ascending=False).head(5).iterrows():
    st.markdown(f"> {r['sentence']}  \n<small>positivity {r['net']:+.2f}</small>", unsafe_allow_html=True)

# ---------------- context ----------------
st.subheader("Why they might say it")
context = engine.context_flags(text)
for name, why, hit in context:
    st.markdown(f"**{name}.** {why}  \n> {hit}")
if not context:
    st.write("Nothing in the text suggests a special reason to sound upbeat (no capital raise, deal, "
             "leadership change, impairment, guidance change or debt pressure mentioned).")

# ---------------- chart ----------------
st.subheader("Where this release sits")
hist = alt.Chart(bench).mark_bar(color=BLUE, opacity=0.45, cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
    x=alt.X("tone_net:Q", bin=alt.Bin(maxbins=30), title="Tone (FinBERT, -1 to +1)"),
    y=alt.Y("count():Q", title="Releases"),
    tooltip=[alt.Tooltip("count():Q", title="Releases")])
mark = pd.DataFrame({"tone_net": [tone], "label": ["This release"]})
rule = alt.Chart(mark).mark_rule(color=ORANGE, strokeWidth=2).encode(x="tone_net:Q")
label = alt.Chart(mark).mark_text(align="left", dx=5, dy=-120, fontWeight="bold").encode(x="tone_net:Q", text="label:N")
st.altair_chart(hist + rule + label, use_container_width=True)
st.caption(f"Bars: tone of the {len(bench)} ASX 50 results releases (2022-2026) we've scored. Line: this release.")

# ---------------- method ----------------
with st.expander("How this works, and what it can't tell you"):
    st.markdown(f"""
- **Tone**: [FinBERT](https://huggingface.co/ProsusAI/finbert), a free model trained on financial text, rates each of the
  first 200 sentences as positive, negative or neutral. Tone = average of P(positive) - P(negative), shown as a
  1-10 rank against {len(bench)} past ASX results releases.
- **Numbers**: read from the Appendix 4E/4D, results tables and sentences, with a confidence flag.
  Profit change uses underlying NPAT where reported, otherwise statutory.
- **Spin**: tone minus the tone you'd expect for that profit change, based on how {model['n']} past releases sounded.
- **What it can't do**: in our research on {model['n']} ASX releases, neither tone nor spin predicted the share price
  reaction around the release (correlation about 0). Prices react to surprise against analysts' expectations, which an
  announcement alone doesn't reveal. Use this to read announcements critically, **not** to decide whether to buy or sell.
- This is general information, not financial advice.
""")
