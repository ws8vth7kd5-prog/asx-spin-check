"""Step 1 scoring as a script: FinBERT tone + CAR for every PDF in ./announcements.

Same method as asx_tone_engine3.ipynb:
    tone_net = mean over the first 200 clean sentences of FinBERT P(positive) - P(negative)
    car      = stock minus ASX 200 daily returns, summed over trading days -1 to +1
Results go to tone_all.csv; files already in it are skipped.

    python tone.py           score everything not yet scored
    python tone.py --check   score 8 Step 1 PDFs and compare with tone_results.csv
"""
import glob, os, sys

import numpy as np
import pandas as pd
import yfinance as yf

from engine import MAX_SENTENCES, load_finbert, pdf_text, score_sentences, summarise, to_sentences

FOLDER = "announcements"
OUT = "tone_all.csv"
INDEX = "^AXJO"
WINDOW = (-1, 1)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# text cleaning and FinBERT scoring live in engine.py (shared with the website)
finbert = load_finbert()


def tone_scores(sents):
    return summarise(score_sentences(finbert, sents))


# ---------- CAR ----------
_prices = {}


def closes(symbol):
    if symbol not in _prices:
        px = yf.download(symbol, start="2021-11-01", auto_adjust=True, progress=False)["Close"]
        if isinstance(px, pd.DataFrame):
            px = px.iloc[:, 0]
        _prices[symbol] = px.dropna()
    return _prices[symbol]


def car(ticker, date):
    stock = closes(f"{ticker}.AX").pct_change()
    market = closes(INDEX).pct_change()
    ar = (stock - market).dropna()
    if ar.empty:
        return np.nan
    day0 = ar.index.searchsorted(date)   # first trading day on/after release
    lo, hi = day0 + WINDOW[0], day0 + WINDOW[1]
    if lo < 0 or hi >= len(ar):
        return np.nan
    return ar.iloc[lo:hi + 1].sum()


def score(path):
    ticker, date = os.path.basename(path)[:-4].split("_")
    sents = to_sentences(pdf_text(path))[:MAX_SENTENCES]
    if not sents:
        print(f"{ticker} {date}: no usable text (scanned PDF?) - skipped")
        return None
    row = {"ticker": ticker, "date": date, **tone_scores(sents)}
    row["car"] = car(ticker, pd.Timestamp(date))
    row["car_pct"] = row["car"] * 100
    return row


def check():
    old = pd.read_csv("tone_results.csv").sample(8, random_state=0)
    for _, o in old.iterrows():
        new = score(os.path.join(FOLDER, f"{o.ticker}_{o.date}.pdf"))
        print(f"{o.ticker} {o.date}: tone old {o.tone_net:.4f} new {new['tone_net']:.4f} | "
              f"sentences old {o.n_sentences} new {new['n_sentences']} | car old {o.car_pct:.2f} new {new['car_pct']:.2f}")


def main():
    done = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=["ticker", "date"])
    have = set(done["ticker"] + "_" + done["date"].astype(str))
    rows = []
    todo = [p for p in sorted(glob.glob(os.path.join(FOLDER, "*.pdf"))) if os.path.basename(p)[:-4] not in have]
    print(f"{len(todo)} PDFs to score", flush=True)
    for i, path in enumerate(todo, 1):
        print(f"  reading {os.path.basename(path)} ...", flush=True)
        try:
            row = score(path)
        except Exception as e:
            print(f"{os.path.basename(path)}: FAILED - {e}")
            continue
        if row:
            rows.append(row)
            print(f"[{i}/{len(todo)}] {row['ticker']} {row['date']}: tone {row['tone_net']:.3f}, CAR {row['car_pct']:.2f}%",
                  flush=True)
            pd.concat([done, pd.DataFrame(rows)]).to_csv(OUT, index=False)   # save after every file
    print(f"Saved {OUT}")


if __name__ == "__main__":
    check() if sys.argv[1:] == ["--check"] else main()
