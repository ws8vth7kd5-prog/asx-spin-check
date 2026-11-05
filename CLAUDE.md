# ASX Announcement Tone & Spin Engine

## What this is
A side project by a UQ Finance / Business Analytics student. Goal: a free tool that reads an ASX company's results announcement and reports (1) how positive the language is and (2) whether that tone is justified by the actual numbers ("spin"). Starts as research, later a simple Streamlit website (paste/upload an announcement, get scores), later possibly ticker lookup.

## Working style
- Explain each step in plain language as you go; the student wants to learn, not just receive code.
- Keep answers short and direct.
- Free tools only: no paid APIs or tokens. FinBERT (ProsusAI/finbert, Hugging Face) for sentiment, yfinance for prices, pdfplumber for PDFs.
- Output is analysis, never buy/sell advice (Australian financial advice licensing).

## Step 1 — done (asx_tone_engine.ipynb, tone_results.csv)
- 19 ASX 50 companies (ANZ dropped), up to 6 results announcements each, 2024–2026 → 102 announcements.
- Announcements fetched from ASX's public pages (asx.com.au/asx/v2/statistics/announcements.do), filtered to the company's own results release (excludes AGMs, shareholder emails, transcripts, quarterly updates, NZ subsidiaries).
- Tone = mean over first 200 sentences of FinBERT P(positive) − P(negative).
- Reaction = CAR, stock minus ASX 200 (^AXJO) daily returns, days −1 to +1 around release date.
- Findings: tone level vs CAR r = −0.12 (p = 0.24); tone change vs previous release r = +0.11 (p = 0.34); tone change vs same period last year r = +0.14 (p = 0.27). No signal. Tone alone doesn't predict reactions. Big tone swings partly an artefact of mixing short releases with full annual reports.

## Step 2 — results
- Env: `.venv` (Python 3.12, torch CPU + transformers). Run scripts with `.venv\Scripts\python.exe`.
- Sample expanded: 43 ASX 50 companies (AMC dropped: SEC filings), 2022–2026 → 384 releases (announcements_index.csv lists headline per file). fetch_announcements.py --discover.
- tone.py = Step 1 notebook scoring as a script (verified identical on 8 Step 1 files) → tone_all.csv (384, all with CAR).
- extract_headlines.py → headline_numbers.csv: profit % change for 261/384 (half/full-year guess handles "1H FY2026"; 378/383 correct vs headlines). Hand-check: round 1 21/21; round 2 ~17/19 checked, 2 errors fixed (IAG reversed columns with arrow-image signs; SHL division/organic growth). test_extract.py = regression tests (19) for the extraction rules — run after any rule change.
- spin.py → spin_results.csv, spin_tests.csv, spin_scatter.png. Profit = underlying if found, else statutory; signed-log transformed.
- Numbers explain tone: r = 0.16 (p = 0.010) pooled, 0.15 (p = 0.017) within company. Spin is a meaningful measure of tone vs numbers.
- Spin vs CAR (n = 260): pooled r = 0.01 (p = 0.92); per-company r = 0.04 (p = 0.53); high/medium only r ≈ 0; trimmed r ≈ +0.11 (p ≈ 0.08, wrong direction). The −0.15 from the 74-release sample was noise. Tone alone (r = 0.02) and profit change alone (r = 0.05) don't predict CAR either: reactions are driven by surprise vs analyst expectations, which we don't have.
- Conclusion: spin is useful as a description ("sounds rosier than its numbers"), not a predictor. Site must not claim it predicts price moves.

## Step 2 — plan: spin score
1. Extract headline numbers from each announcement PDF: statutory/underlying NPAT and revenue, and their % change vs prior corresponding period (most releases state these in the first page or two). Store with a confidence flag; check a sample by hand.
2. Spin = tone that isn't explained by the numbers, e.g. residual from regressing tone on profit % change (pooled, or per company).
3. Test whether higher spin goes with worse CAR. Report correlation, p-value, and a scatter chart; check robustness without outliers.
4. Keep the PDFs in ./announcements and results in CSVs so nothing needs re-downloading.

## Step 3 — website (built, not yet deployed)
- app.py (Streamlit). Run: `.venv\Scripts\streamlit run app.py` (or preview "tone-site" in .claude/launch.json). Restart the server after editing engine.py / extract_headlines.py (Streamlit only reloads app.py).
- engine.py = shared code for research + site (text, FinBERT, spin, context flags). tone.py imports it; verified identical scores.
- Tone and spin shown as 1–10 percentile vs data/benchmark.csv (384 releases); spin uses data/spin_model.json. Both written by spin.py.
- Sections: scores, summary, key numbers (+confidence, source text), red flags (underlying vs statutory gap >15pts; profit down but tone top 30%; most upbeat sentences), "why they might say it" (capital raise, takeover interest, deals, leadership change, impairments, guidance change, debt), tone histogram, method + disclaimer stating spin doesn't predict price moves.
- Look: "ASX Spin Check", always-black theme (.streamlit/config.toml base = dark). Speed-dial logo; tone/spin shown as half-circle dials with an animated needle; profit card tinted green/red; key numbers as an HTML table. Streamlit strips inline <svg> from st.html, so dials are SVG data-URI <img> tags with the CSS animation inside the SVG.
- make_space.py builds ./space (includes .streamlit/config.toml and a GitHub README). Hosting: Hugging Face Docker/Gradio Spaces now need PRO (paid), so deploy free on Streamlit Community Cloud from a public GitHub repo holding the contents of ./space (Python 3.12; requirements use CPU-only torch). The Dockerfile is kept for HF if ever on PRO.

## Later
- Expand benchmark to ASX 200, 5 years (use historical constituents to avoid survivorship bias); test whether spin predicts reactions for small caps with little analyst coverage.
- Ticker lookup that fetches the latest release automatically.
