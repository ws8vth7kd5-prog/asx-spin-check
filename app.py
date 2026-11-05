"""ASX results tone & spin - Streamlit website.

Run locally:  .venv\\Scripts\\streamlit run app.py
Scores are compared against data/benchmark.csv (every release scored in the research),
so tone 9/10 means "more upbeat than ~90% of ASX results releases we've scored".
"""
import base64
import html
import io
import math
import os
import re

import altair as alt
import pandas as pd
import streamlit as st

import engine
import extract_headlines as xh

st.set_page_config(page_title="ASX Spin Check", page_icon=":material/speed:", layout="centered")

BLUE, ORANGE, GREEN, RED = "#3987e5", "#eb6834", "#0ca30c", "#e34948"
METRIC_NAMES = {"revenue": "Revenue", "npat_stat": "Statutory NPAT", "npat_underlying": "Underlying NPAT"}
IN_TEXT = {"revenue": "revenue", "npat_stat": "statutory NPAT", "npat_underlying": "underlying NPAT"}

# dial zones: (colour, label). Tone = one hue getting brighter; spin = blue / grey / orange (diverging)
TONE_ZONES = [("#1d3f6e", "Restrained"), ("#2a78d6", "Typical"), ("#6da7ec", "Very upbeat")]
SPIN_ZONES = [(BLUE, "Plays it down"), ("#5a5955", "In line with numbers"), (ORANGE, "Rosier than the numbers")]

st.html("""
<style>
.brand {display: flex; align-items: center; gap: 16px; margin: .5rem 0 1.4rem;}
.brand-name {font-size: 2.2rem; font-weight: 800; letter-spacing: -.02em; line-height: 1.1;}
.brand-tag {opacity: .7; font-size: 1.02rem; margin-top: 2px;}
.tc-card {border: 1px solid rgba(255,255,255,.12); border-radius: 14px; padding: 14px 16px; height: 100%;
          background: #0d0d0d; text-align: center; min-height: 300px;}
.tc-label {font-size: .76rem; text-transform: uppercase; letter-spacing: .08em; opacity: .65; font-weight: 700;}
.g-value {font-size: 2.1rem; font-weight: 800; line-height: 1; margin-top: 6px;}
.g-value span {font-size: 1rem; font-weight: 500; opacity: .55; margin-left: 2px;}
.tc-band {font-weight: 700; margin-top: .45rem;}
.tc-note {font-size: .82rem; opacity: .65; margin-top: .15rem;}
.profit {display: flex; flex-direction: column; justify-content: center;}
.profit.up {background: rgba(12,163,12,.14); border-color: rgba(12,163,12,.65);}
.profit.down {background: rgba(227,73,72,.14); border-color: rgba(227,73,72,.65);}
.profit .big {font-size: 2.6rem; font-weight: 800; margin: .6rem 0 .2rem;}
.up .big, .pill.up {color: #3fcf3f;} .down .big, .pill.down {color: #ff6b6a;}
.kn {width: 100%; border-collapse: separate; border-spacing: 0; border: 1px solid rgba(255,255,255,.12);
      border-radius: 12px; overflow: hidden; font-size: .93rem;}
.kn th {text-align: left; font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; opacity: .6;
        font-weight: 700; padding: 10px 14px; background: #0d0d0d; border-bottom: 1px solid rgba(255,255,255,.12);}
.kn td {padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,.07); vertical-align: top;}
.kn tr:last-child td {border-bottom: none;}
.kn .name {font-weight: 700; white-space: nowrap;}
.pill {display: inline-block; padding: 3px 10px; border-radius: 999px; font-weight: 700; white-space: nowrap;}
.pill.up {background: rgba(12,163,12,.16);} .pill.down {background: rgba(227,73,72,.16);}
.pill.none {opacity: .45; padding-left: 0;}
.conf {white-space: nowrap;} .dot {display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px;}
.kn details summary {cursor: pointer; opacity: .75; font-size: .85rem;}
.kn details p {margin: .4rem 0 0; font-size: .85rem; opacity: .85;}
.tc-quote {border-left: 3px solid #3987e5; padding: .35rem 0 .35rem .9rem; margin: 0 0 .8rem;}
.tc-quote small {opacity: .6;}
@media (max-width: 640px) {.kn .src {display: none;} .brand-name {font-size: 1.7rem;} .tc-card {min-height: 0;}}
</style>
""")


# ---------------- drawing helpers ----------------
def _arc(deg1, deg2, r, cx=100, cy=100):
    """SVG path for an arc of the half-circle, from angle deg1 down to deg2 (180 = left, 0 = right)."""
    x1, y1 = cx + r * math.cos(math.radians(deg1)), cy - r * math.sin(math.radians(deg1))
    x2, y2 = cx + r * math.cos(math.radians(deg2)), cy - r * math.sin(math.radians(deg2))
    return f"M{x1:.1f},{y1:.1f} A{r},{r} 0 0 1 {x2:.1f},{y2:.1f}"


def dial_svg(score, zones, width="100%", animate=True, needle_colour="#f0efec", ticks=True):
    """Half-circle dial with three coloured zones and a needle at `score` (1-10), as an <img>.
    Streamlit strips inline <svg> from custom HTML, so the drawing is passed as an image; the needle
    sweep is a CSS animation inside the image, which browsers still play."""
    segs = "".join(f'<path d="{_arc(180 - i * 60 - (0 if i == 0 else 1.5), 180 - (i + 1) * 60 + (0 if i == 2 else 1.5), 78)}" '
                   f'stroke="{c}" stroke-width="18" fill="none"/>' for i, (c, _) in enumerate(zones))
    rot = -90 + (min(max(score, 1), 10) - 1) / 9 * 180
    anim = (f"<style>.n{{transform-origin:100px 100px;transform:rotate({rot:.1f}deg);"
            f"animation:s 1.4s cubic-bezier(.2,.9,.25,1) both}}"
            f"@keyframes s{{from{{transform:rotate(-90deg)}}to{{transform:rotate({rot:.1f}deg)}}}}"
            f"@media (prefers-reduced-motion:reduce){{.n{{animation:none}}}}</style>") if animate else ""
    needle = 'class="n"' if animate else f'transform="rotate({rot:.1f} 100 100)"'
    labels = ('<text x="22" y="111" font-size="10" fill="#f0efec" opacity=".5" text-anchor="middle">1</text>'
              '<text x="178" y="111" font-size="10" fill="#f0efec" opacity=".5" text-anchor="middle">10</text>') if ticks else ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 112">{anim}{segs}'
           f'<g {needle}><line x1="100" y1="100" x2="100" y2="34" stroke="{needle_colour}" stroke-width="4" '
           f'stroke-linecap="round"/><circle cx="100" cy="100" r="8" fill="{needle_colour}"/></g>{labels}</svg>')
    data = base64.b64encode(svg.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" width="{width}" alt="dial at {score:.1f} out of 10">'


LOGO = dial_svg(7.8, SPIN_ZONES, width="72", animate=False, ticks=False)


def gauge_card(label, score, zones, note):
    zone = zones[0 if score < 4 else (2 if score > 7 else 1)][1]
    return (f'<div class="tc-card"><div class="tc-label">{label}</div>{dial_svg(score, zones)}'
            f'<div class="g-value">{score:.1f}<span>/10</span></div><div class="tc-band">{zone}</div>'
            f'<div class="tc-note">{note}</div></div>')


def profit_card(pct, basis):
    if pct is None:
        return ('<div class="tc-card profit"><div class="tc-label">Profit change</div>'
                '<div class="big" style="opacity:.45">not found</div><div class="tc-note">No profit figure found</div></div>')
    cls, sym = ("up", "▲") if pct >= 0 else ("down", "▼")
    return (f'<div class="tc-card profit {cls}"><div class="tc-label">Profit change</div>'
            f'<div class="big">{sym} {abs(pct):.1f}%</div><div class="tc-band">{basis.capitalize()} NPAT</div>'
            f'<div class="tc-note">vs same period last year</div></div>')


def pill(p):
    if p is None or pd.isna(p):
        return '<span class="pill none">not found</span>'
    cls, sym = ("up", "▲") if p >= 0 else ("down", "▼")
    return f'<span class="pill {cls}">{sym} {abs(p):.1f}%</span>'


CONF = {"high": (GREEN, "High"), "medium": ("#eda100", "Medium"), "low": (RED, "Low")}


def numbers_table(numbers):
    rows = []
    for m, name in METRIC_NAMES.items():
        n = numbers.get(m)
        if n:
            colour, word = CONF.get(n["confidence"], ("#888", n["confidence"]))
            conf = f'<span class="conf"><span class="dot" style="background:{colour}"></span>{word}</span>'
            src = (f'<details><summary>Page {int(n["page"])}</summary><p>{html.escape(str(n["text"]))}</p></details>')
            rows.append(f'<tr><td class="name">{name}</td><td>{pill(n["pct"])}</td><td>{conf}</td><td class="src">{src}</td></tr>')
        else:
            rows.append(f'<tr><td class="name">{name}</td><td>{pill(None)}</td><td></td><td class="src"></td></tr>')
    return ('<table class="kn"><thead><tr><th>Measure</th><th>Change vs last year</th><th>Confidence</th>'
            '<th class="src">Source</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


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


def where_chart(values, this, title):
    """Histogram of past releases with this release marked."""
    df = pd.DataFrame({"v": pd.Series(values).dropna()})
    hist = alt.Chart(df).mark_bar(color=BLUE, opacity=0.55, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("v:Q", bin=alt.Bin(maxbins=30), title=title),
        y=alt.Y("count():Q", title="Releases"),
        tooltip=[alt.Tooltip("v:Q", bin=alt.Bin(maxbins=30), title=title), alt.Tooltip("count():Q", title="Releases")])
    mark = pd.DataFrame({"v": [this], "label": ["This release"]})
    rule = alt.Chart(mark).mark_rule(color=ORANGE, strokeWidth=2.5).encode(x="v:Q")
    text = alt.Chart(mark).mark_text(align="left", dx=6, fontWeight="bold", color=ORANGE).encode(
        x="v:Q", y=alt.value(12), text="label:N")   # pinned near the top of the plot
    return (hist + rule + text).properties(height=260).configure_axis(grid=False).configure_view(strokeWidth=0)


# ---------------- header + input ----------------
st.html(f'<div class="brand">{LOGO}<div><div class="brand-name">ASX Spin Check</div>'
        f'<div class="brand-tag">Is an ASX results announcement more upbeat than its numbers?</div></div></div>')

with st.container(border=True):
    tab_pdf, tab_text = st.tabs([":material/upload_file: Upload PDF", ":material/content_paste: Paste text"])
    with tab_pdf:
        upload = st.file_uploader("Results announcement (PDF)", type="pdf", label_visibility="collapsed")
        examples = sorted(os.listdir("announcements")) if os.path.isdir("announcements") else []
        example = st.selectbox("...or try one we've scored", [""] + examples) if examples else ""
    with tab_text:
        pasted = st.text_area("Paste the announcement text", height=180, label_visibility="collapsed",
                              placeholder="Paste the announcement text here...")
    ticker_in = st.text_input("ASX ticker (optional)", max_chars=4, placeholder="e.g. WES",
                              help="Used to compare with the company's own past releases.").strip().upper()
    go = st.button("Analyse", type="primary", icon=":material/speed:", width="stretch")

if not go:
    st.write("")
    c1, c2, c3 = st.columns(3)
    for col, icon, head, body in [
        (c1, ":material/record_voice_over:", "Tone", "How upbeat the language is, ranked against 384 ASX results releases."),
        (c2, ":material/balance:", "Spin", "Whether the tone is rosier than the profit numbers would justify."),
        (c3, ":material/flag:", "Red flags", "Gaps between underlying and statutory profit, the most 'selling' sentences, "
                                             "and reasons management might want to sound upbeat."),
    ]:
        with col.container(border=True):
            st.markdown(f"**{icon} {head}**")
            st.caption(body)
    st.caption("Free analysis tool. Not financial advice.")
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
    st.warning("Upload a PDF or paste some text first.", icon=":material/info:")
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
st.write("")
c1, c2, c3 = st.columns(3)
with c1:
    st.html(gauge_card("Tone", tone10, TONE_ZONES, f"More upbeat than {tone_share:.0%} of releases"))
with c2:
    if profit_pct is not None:
        st.html(gauge_card("Spin", spin10, SPIN_ZONES, "Tone vs releases with similar profit growth"))
    else:
        st.html('<div class="tc-card"><div class="tc-label">Spin</div><div class="g-value" style="margin-top:4.5rem;'
                'opacity:.45">n/a</div><div class="tc-note">Needs a profit figure, and none was found</div></div>')
with c3:
    st.html(profit_card(profit_pct, basis))

# ---------------- summary ----------------
st.subheader(":material/summarize: Summary")
nums = [f"{IN_TEXT[m]} {fmt_pct(numbers[m]['pct'])}" for m in METRIC_NAMES if numbers.get(m)]
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
with st.container(border=True):
    st.markdown("\n".join("- " + line for line in lines))

# ---------------- numbers ----------------
st.subheader(":material/table_chart: Key numbers")
st.html(numbers_table(numbers))
st.caption("Found automatically and compared with the same period last year. High confidence = from the "
           "Appendix 4E/4D or a table we could cross-check. Click a page number to see the source text.")

# ---------------- red flags ----------------
st.subheader(":material/flag: Red flags")
flags = 0
u, s = numbers.get("npat_underlying"), numbers.get("npat_stat")
if u and s and u["pct"] - s["pct"] > 15:
    st.warning(f"**Underlying profit ({fmt_pct(u['pct'])}) is much better than statutory profit ({fmt_pct(s['pct'])}).** "
               "Check what was excluded from 'underlying' and whether it's really one-off.", icon=":material/warning:")
    flags += 1
if profit_pct is not None and profit_pct < 0 and tone_share > 0.7:
    st.warning(f"**Profit fell ({fmt_pct(profit_pct)}) but the tone is more upbeat than {tone_share:.0%} of releases.**",
               icon=":material/warning:")
    flags += 1
if not flags and profit_pct is None:
    st.info("Couldn't check the number-based red flags: no profit figures were found.", icon=":material/info:")
elif not flags:
    st.success("No number-based red flags.", icon=":material/check_circle:")

with st.expander(":material/format_quote: Most upbeat sentences: the ones doing the most 'selling'", expanded=True):
    for _, r in scored.sort_values("net", ascending=False).head(5).iterrows():
        st.html(f'<div class="tc-quote">{html.escape(r["sentence"])}<br><small>positivity {r["net"]:+.2f}</small></div>')

# ---------------- context ----------------
st.subheader(":material/psychology: Why they might say it")
context = engine.context_flags(text)
for name, why, hit in context:
    with st.container(border=True):
        st.markdown(f"**{name}**")
        st.caption(why)
        st.html(f'<div class="tc-quote">{html.escape(hit)}</div>')
if not context:
    st.info("Nothing in the text suggests a special reason to sound upbeat (no capital raise, takeover interest, "
            "deal, leadership change, impairment, guidance change or debt pressure mentioned).", icon=":material/info:")

# ---------------- charts ----------------
st.subheader(":material/bar_chart: Where this release sits")
tabs = st.tabs(["Tone", "Spin"])
with tabs[0]:
    st.altair_chart(where_chart(bench["tone_net"], tone, "Tone (FinBERT, -1 to +1)"), width="stretch")
with tabs[1]:
    if profit_pct is not None:
        st.altair_chart(where_chart(bench["spin_pooled"], spin, "Spin (tone above what the profit change predicts)"),
                        width="stretch")
    else:
        st.caption("Spin needs a profit figure, and none was found.")
st.caption(f"Bars: the {len(bench)} ASX 50 results releases (2022-2026) we've scored. Orange line: this release.")

# ---------------- method ----------------
with st.expander(":material/help: How this works, and what it can't tell you"):
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
