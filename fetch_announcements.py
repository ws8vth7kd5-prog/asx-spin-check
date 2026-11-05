"""Download results announcement PDFs into ./announcements.

    python fetch_announcements.py [TICKER ...]
        Re-download the Step 1 documents: the (ticker, date) pairs in tone_results.csv.
    python fetch_announcements.py --discover [TICKER ...]
        Find every results release for TICKERS in YEARS (one per reporting season, same
        headline rules as Step 1) and download any we don't have. Writes announcements_index.csv.
Files already downloaded are skipped.
"""
import os, re, sys, time
from html import unescape

import pandas as pd
import requests

FOLDER = "announcements"
BASE = "https://www.asx.com.au"
YEARS = range(2022, 2027)
# Step 1's 19 companies (ANZ dropped) plus more ASX 50 names
TICKERS = ["ALL", "BHP", "CBA", "COL", "CSL", "FMG", "GMG", "MQG", "NAB", "QBE", "REA", "RIO", "STO",
           "TCL", "TLS", "WBC", "WDS", "WES", "WOW",
           "SUN", "IAG", "ORG", "BXB", "CPU", "XRO", "WTC", "SHL", "COH", "TWE", "NST", "S32", "MIN",
           "ASX", "SCG", "QAN", "APA", "BSL", "CAR", "SOL", "ALQ", "RHC", "MPL", "NXT"]
# AMC (Amcor) left out: US company whose ASX "results" are SEC 10-K/10-Q filings
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (student research project)"})

# Same headline rules as the Step 1 notebook
EXCLUDE = ["meeting", "agm", "email", "letter", "shareholder", "items impacting", "presentation",
           "webcast", "teleconference", "briefing", "investor", "dividend", "distribution",
           " nz", "new zealand", "asb ", "bnz", "date of", "timing", "notice", "pre-result",
           "preliminary final report", "trading update", "transcript", "quarter", "production",
           # added when expanding the sample: wrong document type, or a price move driven by something else
           "speech", "revised", "raising", "placement", "form 10", "form 8-k"]
PERIOD = re.compile(r"\b(fy|hy|1h|2h)\s?\d*\b|full[- ]year|half[- ]year|interim|annual|financial year")


def result_rank(headline):
    h = " " + headline.lower() + " "
    if any(w in h for w in EXCLUDE):
        return 0
    period = bool(PERIOD.search(h))
    if "result" in h and period and any(w in h for w in ["announcement", "release", "media", "asx"]):
        return 4
    if "appendix 4e" in h or "appendix 4d" in h:
        return 3
    if "result" in h and period:
        return 3
    if "profit" in h and period:
        return 2
    return 0


def parse_listing(html):
    rows = []
    for tr in re.split(r"<tr[\s>]", html)[1:]:
        date = re.search(r"(\d{2}/\d{2}/\d{4})", tr)
        link = re.search(r'href="([^"]*displayAnnouncement\.do[^"]*idsId=(\d+)[^"]*)"[^>]*>\s*(.*?)\s*<', tr, re.S)
        if not (date and link):
            continue
        href = unescape(link.group(1))
        rows.append({
            "date": pd.to_datetime(date.group(1), dayfirst=True),
            "url": BASE + href if href.startswith("/") else href,
            "headline": re.sub(r"\s+", " ", unescape(link.group(3))).strip(),
        })
    return rows


def list_announcements(ticker, year):
    url = f"{BASE}/asx/v2/statistics/announcements.do?by=asxCode&asxCode={ticker}&timeframe=Y&year={year}"
    r = S.get(url, timeout=30)
    r.raise_for_status()
    time.sleep(1)
    return parse_listing(r.text)


def download_pdf(url, path):
    r = S.get(url, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        # ASX shows a terms page first; the real PDF link is inside it
        m = (re.search(r'name="pdfURL"\s+value="([^"]+)"', r.text)
             or re.search(r'(https?://announcements\.asx\.com\.au/asxpdf/[^"\'\s]+\.pdf)', r.text))
        if not m:
            raise RuntimeError("couldn't find the PDF link on the ASX page")
        r = S.get(unescape(m.group(1)), timeout=60)
        r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError("download wasn't a PDF")
    with open(path, "wb") as f:
        f.write(r.content)


def pick_results(rows):
    """One document per results season (best headline within ~6 weeks), most recent first."""
    cands = [dict(r, rank=result_rank(r["headline"])) for r in rows]
    cands = sorted([c for c in cands if c["rank"] >= 2], key=lambda c: c["date"], reverse=True)
    picks = []
    for c in cands:
        if picks and (picks[-1]["date"] - c["date"]).days <= 45:
            if c["rank"] > picks[-1]["rank"]:
                picks[-1] = c
        else:
            picks.append(c)
    return picks


def discover(tickers):
    os.makedirs(FOLDER, exist_ok=True)
    index = []
    for t in tickers:
        try:
            rows = [r for y in YEARS for r in list_announcements(t, y)]
        except Exception as e:
            print(f"{t}: listing FAILED - {e}")
            continue
        picks = pick_results(rows)
        if not picks:
            print(f"{t}: no results announcements found")
        for p in picks:
            fname = f"{t}_{p['date'].date()}.pdf"
            path = os.path.join(FOLDER, fname)
            status = "already had"
            if not os.path.exists(path):
                try:
                    download_pdf(p["url"], path)
                    time.sleep(1)
                    status = "saved"
                except Exception as e:
                    status = f"failed: {e}"
            print(f"{fname}: {status}  ({p['headline']})")
            index.append({"ticker": t, "date": p["date"].date(), "file": fname, "headline": p["headline"],
                          "rank": p["rank"], "status": status})
    index = pd.DataFrame(index)
    if os.path.exists("announcements_index.csv"):   # keep rows for tickers not in this run
        old = pd.read_csv("announcements_index.csv", encoding="utf-8-sig")
        index = pd.concat([old[~old["ticker"].isin(tickers)], index])
    index.to_csv("announcements_index.csv", index=False, encoding="utf-8-sig")


def main(only=None):
    os.makedirs(FOLDER, exist_ok=True)
    wanted = pd.read_csv("tone_results.csv", parse_dates=["date"])[["ticker", "date"]]
    if only:
        wanted = wanted[wanted["ticker"].isin(only)]
    log = []
    for ticker, grp in wanted.groupby("ticker"):
        listing = {}
        for _, row in grp.iterrows():
            fname = f"{ticker}_{row['date'].date()}.pdf"
            path = os.path.join(FOLDER, fname)
            if os.path.exists(path):
                log.append({"file": fname, "headline": "", "status": "already had"})
                continue
            y = row["date"].year
            if y not in listing:
                listing[y] = list_announcements(ticker, y)
            same_day = [dict(a, rank=result_rank(a["headline"])) for a in listing[y] if a["date"] == row["date"]]
            same_day = sorted([a for a in same_day if a["rank"] >= 2], key=lambda a: -a["rank"])
            if not same_day:
                print(f"{fname}: no results release found on that date")
                log.append({"file": fname, "headline": "", "status": "not found"})
                continue
            best = same_day[0]
            try:
                download_pdf(best["url"], path)
                time.sleep(1)
                print(f"{fname}: saved  ({best['headline']})")
                log.append({"file": fname, "headline": best["headline"], "status": "saved"})
            except Exception as e:
                print(f"{fname}: FAILED - {e}")
                log.append({"file": fname, "headline": best["headline"], "status": f"failed: {e}"})
    pd.DataFrame(log).to_csv("download_log.csv", index=False)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--discover"]:
        discover(args[1:] or TICKERS)
    else:
        main(args or None)
