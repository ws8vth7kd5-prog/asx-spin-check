"""Shared analysis code: used by tone.py (research) and app.py (website), so both score
announcements exactly the same way.

    text    : pdf_text, to_sentences       (Step 1 notebook cleaning, unchanged)
    tone    : load_finbert, score_sentences, summarise
    spin    : profit_change, signed_log, spin_of
"""
import json
import re

import numpy as np
import pandas as pd
import pdfplumber

MAX_SENTENCES = 200


# ---------- text ----------
def to_sentences(text):
    text = re.sub(r"-\n", "", text)          # rejoin hyphenated line breaks
    text = re.sub(r"\s*\n\s*", " ", text)    # join lines
    text = re.sub(r"\s{2,}", " ", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    keep = []
    for s in parts:
        s = s.strip()
        words = s.split()
        if len(words) < 6 or len(words) > 80:
            continue
        letters = sum(c.isalpha() for c in s)
        if letters / max(len(s), 1) < 0.6:   # mostly numbers = table row
            continue
        keep.append(s)
    return keep


def pdf_text(pdf_file):
    """Text of a PDF (path or file object), stopping once we're well past MAX_SENTENCES.
    Only the first 200 sentences are scored, so the result is the same as reading every
    page - and it avoids long annual reports that can make pdfplumber hang."""
    pages = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
            if len(to_sentences("\n".join(pages[:-1]))) > MAX_SENTENCES:   # one spare page read
                break
    return "\n".join(pages)


# ---------- tone ----------
def load_finbert():
    import torch
    from transformers import pipeline
    return pipeline("text-classification", model="ProsusAI/finbert", top_k=None, truncation=True,
                    device=0 if torch.cuda.is_available() else -1)


def score_sentences(finbert, sents):
    """One row per sentence: P(positive), P(negative), P(neutral), net = pos - neg, label."""
    out = finbert(sents, batch_size=32)
    p = pd.DataFrame([{r["label"].lower(): r["score"] for r in res} for res in out])
    p.insert(0, "sentence", sents)
    p["net"] = p["positive"] - p["negative"]
    p["label"] = p[["positive", "negative", "neutral"]].idxmax(axis=1)
    return p


def summarise(scored):
    tone = scored["net"].mean()
    return {"n_sentences": len(scored), "tone_net": tone,
            "pct_pos": (scored["label"] == "positive").mean(),
            "pct_neg": (scored["label"] == "negative").mean(),
            "tone_1_10": float(np.clip(5.5 + 4.5 * tone, 1, 10))}


# ---------- context: "why they might say it" ----------
# Situations that give management a reason to sound upbeat. Matched on readable sentences only.
CONTEXT = [
    ("Raising capital", r"capital raising|equity raising|(?:share|institutional|equity) placement|placement of (?:new )?shares|"
                        r"entitlement offer|share purchase plan",
     "Companies raising money have a reason to present results in the best light."),
    ("Takeover interest", r"unsolicited|takeover (?:proposal|offer|bid|approach)|(?:acquisition|non-binding|indicative) proposals?|"
                          r"scheme of arrangement",
     "A company fielding takeover bids has a reason to sound upbeat: it's arguing it's worth more than the offer."),
    ("Recent or pending deal", r"acquisition of|completed the acquisition|merger with|divest",
     "Around a deal, the tone may be aimed at showing the deal is paying off, or at selling it to shareholders."),
    ("Leadership change", r"(?:new|incoming|outgoing) (?:chief executive|ceo|managing director|group ceo)|ceo[- ]designate|"
                          r"appointed (?:as )?(?:the )?(?:chief executive|ceo|managing director)|"
                          r"(?:ceo|chief executive|managing director) (?:transition|succession)|(?:will )?retire as (?:ceo|chief|managing)",
     "New leaders sometimes reset expectations low; departing ones may want to finish on a high."),
    # "amortisation and impairment" is just the definition of EBITDA, not an actual impairment
    ("Impairments or one-offs", r"(?<!amortisation and )(?<!amortisation, and )impairments?\b(?! \(underlying ebitda)|"
                                r"write-?downs?\b|one-off (?:cost|charge|loss|item)s?",
     "One-off losses are often excluded from 'underlying' profit. Compare statutory and underlying."),
    ("Guidance change", r"(?:downgrade|lower|below|revised)\w* (?:\w+ ){0,2}guidance|guidance (?:downgrade|lowered|withdrawn|revised)",
     "A guidance change resets expectations. Upbeat language can soften a downgrade."),
    ("Debt pressure", r"covenant|refinanc|gearing above",
     "Lenders read results too. A positive tone can support refinancing."),
]


def context_flags(text):
    """[(name, why, first sentence that mentions it)] for each situation found in the text."""
    readable = [s for s in to_sentences(text) if len(s.split()) <= 50]   # skip table/footnote blobs
    out = []
    for name, pattern, why in CONTEXT:
        hit = next((s for s in readable if re.search(pattern, s, re.I)), None)
        if hit:
            out.append((name, why, hit))
    return out


# ---------- spin ----------
def profit_change(numbers):
    """The profit % change spin is based on: underlying if we found one, else statutory.
    `numbers` maps metric -> {"pct": ..., "confidence": ...} or None."""
    for metric, basis in [("npat_underlying", "underlying"), ("npat_stat", "statutory")]:
        if numbers.get(metric):
            return numbers[metric]["pct"], basis
    return None, None


def signed_log(pct):
    """Squash big % changes so +312% or -93% don't dominate: sign x log(1 + |pct|)."""
    return np.sign(pct) * np.log1p(np.abs(pct))


def load_spin_model(path="data/spin_model.json"):
    with open(path) as f:
        return json.load(f)


def spin_of(tone_net, profit_pct, model):
    """Tone above what releases with this profit change usually sound like."""
    expected = model["intercept"] + model["slope"] * signed_log(profit_pct)
    return tone_net - expected, expected
