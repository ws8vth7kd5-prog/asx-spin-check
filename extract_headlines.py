"""Step 2.1: pull headline revenue and profit numbers out of each announcement PDF.

For each PDF in ./announcements we look for three metrics and their % change on the
prior corresponding period (pcp):
    revenue          - revenue / sales revenue / operating income (banks) / insurance revenue
    npat_stat        - statutory net profit after tax
    npat_underlying  - underlying / cash / normalised / excl. significant items / NPATA

Candidates come from three kinds of text, in order of how much we trust them:
    4e        Appendix 4E/4D line:  "Profit after tax ... up 2.9% to 1,184.1"       (high)
    table     table row "label  current  prior  x%" where x% matches current/prior  (high)
              (if the % can't be checked against the two numbers it's medium)
    sentence  prose: "NPAT increased by 13.7% to $1,255 million"                    (medium)
              (no $ value found next to the % -> low)
If two equally trusted candidates disagree on the % change, confidence drops one level.

Outputs:
    headline_numbers.csv     one row per announcement (best candidate per metric)
    headline_candidates.csv  every candidate found, for hand-checking
"""
import glob, os, re, sys

import pandas as pd
import pdfplumber

FOLDER = "announcements"
MAX_PAGES = 12

# ---------- what counts as each metric ----------
REVENUE = re.compile(r"\b(total revenue|sales revenue|revenue|net operating income|total operating income|"
                     r"operating income|total income|insurance revenue)\b", re.I)
PROFIT = re.compile(r"\b(net profit|profit after tax|npat|npata|attributable profit|profit attributable|"
                    r"cash earnings|statutory profit|statutory earnings|operating profit|operating earnings|"
                    r"net earnings|profit (inc|incl|excl|excluding|including)\b|profit for the (year|period|half)|"
                    r"profit from continuing)", re.I)
UNDERLYING = re.compile(r"underlying|\bcash\b|normalis|adjusted|\bexcl|excluding|before significant|npata|"
                        r"operating earnings|before amortisation", re.I)
# "operating profit" usually means EBIT (before tax). Only count it if it says "after tax",
# or for Goodman, whose "operating profit" is its underlying after-tax profit.
OPERATING_PROFIT_IS_NPAT = {"GMG"}
# things that look like a metric but aren't the headline figure
NOT_HEADLINE = re.compile(r"per share|\beps\b|\bmargin|before (income )?tax|pre-provision|pre provision|gross profit|\bebit|"
                          r"(?<!and )discontinued|/ ?revenue|\bratio\b|other revenue|other income|by-product|"
                          r"interest income|tax expense|return on|dividend|payout|guidance|\bexpect|outlook|"
                          r"\btarget|\bcosts?\b|average|/dmt|/t\b|per tonne|per boe|/boe", re.I)
NOT_PCP = re.compile(r"half on half|\bhoh\b|prior half|second half|constant currency|\bcc\d*\b|\borganic\b", re.I)
SEGMENT_WORDS = re.compile(r"\bdivision|\bsegment|\bbusiness unit", re.I)   # "Sonic's Radiology division ... revenue"

UP = r"up|increased|increase of|rose|grew|higher|growth of|improved|an increase of"
DOWN = r"down|decreased|decrease of|fell|declined|decline of|lower|a decrease of|a decline of|reduced|decrease|decline|fall"
DIRECTION = rf"(?P<dir>{UP}|{DOWN})"
PCT = r"(?P<pct>\d{1,4}(?:\.\d+)?)\s?(?:%|per\s?cent|pc\b)"
MONEY = r"(?P<cur>A\$|US\$|NZ\$|\$)?\s?(?P<val>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<unit>billion|bn|b\b|million|m\b)?"

# Appendix 4E/4D: "<label> up 11.0% to 6,297.0"
RE_4E = re.compile(rf"^(?P<label>[A-Za-z][^\d%]{{3,90}}?)\s+{DIRECTION}\s+(?:by\s+)?{PCT}\s+to\s+{MONEY}", re.I)
# table row: label then 2-5 numbers, current period first, e.g.
#   "<label> 1,090 1,079 1.0%"  /  "<label> 3,136 (2,986) (2,922) (193%)"  /  "<label> 9,966 11,552 (14) %"
#   "<label> 1,467 1,425 2.9"   /  "<label> 1,104 1,128 (2.1%) 3.7%"      /  "<label> 2,157 1,779"
CELL = r"(?:\(?[+-]?\d[\d,]*(?:\.\d+)?\)?\s?%?\)?|[—–-]\s?%)"
RE_TABLE = re.compile(rf"^(?P<label>[A-Za-z][^\d%]{{3,90}}?)\s+(?P<cells>{CELL}(?:\s+{CELL}){{1,4}})\s*$")
# prose: "... increased 13.7% to $1,255 million" and "... of $7.6 billion, down 20%" / "NPAT $1.90 billion, up 17%"
MONEY_REQ = MONEY.replace("(?P<cur>A\\$|US\\$|NZ\\$|\\$)?", "(?P<cur>A\\$|US\\$|NZ\\$|\\$)")
RE_SENT_A = re.compile(rf"{DIRECTION}\s+(?:by\s+)?(?:approximately\s+|around\s+|~)?{PCT}(?:\s+(?:to|at)\s+{MONEY})?", re.I)
# (the gap can't contain another $ amount: "NPAT was $1.2B, with Underlying NPAT of $822M, up 831%")
RE_SENT_B = re.compile(rf"(?:(?:of|was|to|at)\s+)?{MONEY_REQ}[^.%$]{{0,40}}?{DIRECTION}\s+(?:by\s+)?{PCT}", re.I)
# direction after the %, straight after a $ amount:
#   "$802 million, a 857 per cent increase"  /  "$5,153 million was 9% higher"  /  "$2,718 million (24% lower"
RE_SENT_D = re.compile(rf"{MONEY_REQ}[^.%$]{{0,20}}?(?:\b(?:a|an|was|is)\s+|\()(?:approximately\s+)?{PCT}\s+"
                       rf"(?P<dir>increase|decrease|higher|lower|rise|fall|decline|improvement)\b", re.I)
# "Statutory profit of $1,574 million for FY26, up from $1,481 million"  (no %: work it out)
MONEY_PRIOR = MONEY_REQ.replace("?P<cur>", "?P<cur2>").replace("?P<val>", "?P<val2>").replace("?P<unit>", "?P<unit2>")
RE_SENT_C = re.compile(rf"{MONEY_REQ}[^.%]{{0,40}}?\b(?P<dir>up|down|increased|decreased|higher|lower)\s+(?:from|on|than)\s+{MONEY_PRIOR}", re.I)
# table row with value then % change(s): "Operating profit after tax (continuing ops.) US$647.1m 13% 18%"
# (first % is the reported change; a second one is usually constant currency)
RE_TABLE_V = re.compile(r"^(?P<label>[A-Za-z][^\d%]{3,90}?)\s+(?:A\$|US\$|NZ\$|\$)(?P<val>[\d,]+(?:\.\d+)?)\s?(?P<unit>m|bn)\s+"
                        r"(?P<pct>\(?[+-]?\d[\d.]*\)?\s?%)")
# unit labels inside table labels, e.g. "($000s)", "(A$m)", "(US$ millions)" - the digits upset the label match
UNIT_LABEL = re.compile(r"\s?\((?:US|A|NZ)?\$?\s?'?(?:000s?|m|bn|millions?|billions?)\)", re.I)
# Segment figures: a business-unit name sits just before the metric ("CSL Behring total revenue",
# "Accelerator revenue"). Capitalised words allowed there: generic finance words and the company's name.
GENERIC = set("""group total statutory underlying net sales operating cash reported adjusted normalised
consolidated attributable the our its and of in to after tax profit revenue npat npata income earnings
insurance continuing from operations half full year interim record strong a an with excluding including
excl incl significant items before amortisation key highlights results result financial performance""".split())
COMPANY_WORDS = {
    "ALL": "aristocrat", "BHP": "bhp", "CBA": "commonwealth bank cba", "COL": "coles", "CSL": "csl",
    "FMG": "fortescue", "GMG": "goodman", "MQG": "macquarie", "NAB": "nab national australia bank",
    "QBE": "qbe", "REA": "rea", "RIO": "rio tinto", "STO": "santos", "TCL": "transurban",
    "TLS": "telstra", "WBC": "westpac wbc", "WDS": "woodside", "WES": "wesfarmers", "WOW": "woolworths",
    "SUN": "suncorp", "IAG": "iag", "ORG": "origin", "BXB": "brambles", "CPU": "computershare",
    "XRO": "xero", "WTC": "wisetech", "SHL": "sonic", "COH": "cochlear", "TWE": "treasury wine estates",
    "NST": "northern star", "S32": "south32", "MIN": "mineral resources", "ASX": "asx", "SCG": "scentre",
    "QAN": "qantas", "APA": "apa", "BSL": "bluescope", "CAR": "car", "SOL": "soul patts pattinson",
    "ALQ": "als", "RHC": "ramsay", "MPL": "medibank", "NXT": "nextdc",
}
SEGMENT_PAGE = re.compile(r"segment(al)? (performance|results|review)|divisional (performance|results|review)|"
                          r"business (unit )?performance|performance by (segment|division)", re.I)
# Westpac's half-year releases say "prior period" meaning the previous half, not the pcp
PRIOR_PERIOD = re.compile(r"\b(?:on|v|vs|versus|compared (?:to|with))\s+the\s+prior\s+period", re.I)


def is_segment(label, ticker):
    m = PROFIT.search(label) or REVENUE.search(label)
    if not m:
        return False
    if SEGMENT_WORDS.search(label):
        return True
    before = re.findall(r"[A-Za-z][A-Za-z'&-]*", label[:m.start()])[-2:]
    ok = GENERIC | set(COMPANY_WORDS.get(ticker, "").split())
    return any(w[0].isupper() and w.lower() not in ok and not re.fullmatch(r"[A-Z]{1,3}", w) for w in before)


# "up 5% on 2H23" compares with the previous half, not the pcp. In a full-year release "on 1H25" is too.
VS_2H = re.compile(r"\b(?:on|v|vs|versus|than|compared (?:to|with))\s+(?:the\s+)?2H\s?(?:FY\s?)?\d{2}", re.I)
VS_1H = re.compile(r"\b(?:on|v|vs|versus|than|compared (?:to|with))\s+(?:the\s+)?1H\s?(?:FY\s?)?\d{2}", re.I)
FOOTNOTE = re.compile(r"(?<=[a-z]{3})\d{1,2}\b|(?<=%)\d{1,2}\b")   # "earnings1", "billion1", "14%3"

TRUST = {"4e": 3, "table_checked": 3, "table": 2, "table_computed": 2, "sentence_value": 2, "sentence": 1}
CONF = {3: "high", 2: "medium", 1: "low"}


def classify(label, ticker=None):
    """Which metric (if any) a piece of label text refers to."""
    if not label or NOT_HEADLINE.search(label):
        return None
    if PROFIT.search(label) and REVENUE.search(label):
        return None   # mentions both: usually scrambled text from a graphic, too ambiguous
    if re.search(r"operating profit(?! after tax)", label, re.I):
        return "npat_underlying" if ticker in OPERATING_PROFIT_IS_NPAT else None
    if PROFIT.search(label):
        return "npat_underlying" if UNDERLYING.search(label) else "npat_stat"
    if REVENUE.search(label):
        return "revenue"
    return None


def to_number(s):
    s = s.strip()
    neg = s.startswith("(") or s.startswith("-")
    v = float(re.sub(r"[^\d.]", "", s) or "nan")
    return -v if neg else v


def signed(pct, direction):
    return -float(pct) if re.fullmatch(DOWN, direction.lower()) else float(pct)


def money(m):
    if "val" not in m.re.groupindex or not m.group("val"):
        return None, ""
    unit = (m.group("unit") or "").lower()
    unit = {"b": "bn", "billion": "bn", "million": "m"}.get(unit, unit)
    return float(m.group("val").replace(",", "")), f"{m.group('cur') or ''}{unit}"


def page_texts(page):
    """Page text. Two-column pages are read one column at a time, otherwise
    pdfplumber runs the left and right columns together on each line."""
    x0, top, x1, bottom = page.bbox   # some PDFs' pages don't start at (0, 0)
    mid = (x0 + x1) / 2
    words = page.extract_words()
    crossing = sum(1 for wd in words if wd["x0"] < mid < wd["x1"])
    two_column = len(words) > 100 and crossing / len(words) < 0.01
    if not two_column:
        return [page.extract_text() or ""]
    return [page.crop((x0, top, mid, bottom)).extract_text() or "",
            page.crop((mid, top, x1, bottom)).extract_text() or ""]


def is_full_year(pdf):
    """Rough guess from the first two pages: full-year release or half-year release?"""
    return is_full_year_text(" ".join((p.extract_text() or "") for p in pdf.pages[:2]))


def is_full_year_text(t):
    half = len(re.findall(r"half[- ]year|interim|\b1H\s?\d{2}|\bHY\s?\d{2}|six months|6 months", t, re.I))
    full = len(re.findall(r"full[- ]year|\bFY\s?\d{2}\b|annual|twelve months|12 months|appendix 4e", t, re.I))
    return full > half


def candidates_from_text(text, page_no, full_year, ticker):
    found = []
    text = FOOTNOTE.sub("", text)
    segment_page = bool(SEGMENT_PAGE.search(text))
    # line-based: Appendix 4E lines and table rows
    for line in text.splitlines():
        line = UNIT_LABEL.sub("", line.strip())
        m = RE_4E.match(line)
        if m and (metric := classify(m.group("label"), ticker)):
            val, unit = money(m)
            found.append(dict(metric=metric, pct=signed(m.group("pct"), m.group("dir")), value=val, unit=unit,
                              source="4e", page=page_no, text=line))
            continue
        m = RE_TABLE_V.match(line)
        if m and (metric := classify(m.group("label"), ticker)) and not is_segment(m.group("label"), ticker):
            found.append(dict(metric=metric, pct=to_number(m.group("pct").replace("%", "")),
                              value=float(m.group("val").replace(",", "")), unit=m.group("unit"),
                              source="table", page=page_no, text=line))
            continue
        m = RE_TABLE.match(line)
        if m and (metric := classify(m.group("label"), ticker)) and not is_segment(m.group("label"), ticker):
            cells = re.findall(CELL, m.group("cells"))
            cells = [re.sub(r"\s", "", c) for c in cells]
            if "%" in cells[0] or "%" in cells[1] or re.search(r"\b20\d\d\b", " ".join(cells[:2])):
                continue   # first two cells must be amounts (current, prior), not % or years
            cur, prior = to_number(cells[0]), to_number(cells[1])
            if not prior or prior <= 0 or abs(cur) < 10:
                continue
            calc = round((cur / prior - 1) * 100, 1)
            rest = [0.0 if c.strip("%") in "—–-" else to_number(c.replace("%", "")) for c in cells[2:]]
            # bank-style tables: "this half, prior half, same half last year, % v prior half, % v pcp".
            # If the third column also checks out, it's the pcp, so compare against that.
            third = to_number(cells[2]) if len(cells) >= 4 and "%" not in cells[2] else None
            calc3 = round((cur / third - 1) * 100, 1) if third and third > 0 else None
            # Which column order explains the printed %? Normal order is (current, prior); some tables
            # put last year first (Medibank, IAG). Prefer a match with the printed sign; if none, match
            # the size only - some reports show direction with an arrow image, so the % has no sign.
            # Either way the sign comes from the numbers themselves.
            options = [("calc3", calc3, cur), ("calc", calc, cur)]
            if len(cells) == 3 and cur > 0:
                options.append(("reverse", round((prior / cur - 1) * 100, 1), prior))
            options = [o for o in options if o[1] is not None]
            best = None
            for compare in (lambda c, p: abs(c - p), lambda c, p: abs(abs(c) - abs(p))):
                fits = [(min(compare(c, p) for p in rest), name, c, v) for name, c, v in options if rest]
                fits = [f for f in fits if f[0] < 1.0]
                if fits:
                    best = min(fits) if all(f[1] != "calc3" for f in fits) else next(f for f in fits if f[1] == "calc3")
                    break
            if best:
                source, pct, cur = "table_checked", best[2], best[3]
            elif len(cells) == 2:   # no % column at all: use our own calculation
                source, pct = "table_computed", calc
            elif "%" in cells[-1]:  # a % column that doesn't match (maybe different basis)
                source, pct = "table", rest[-1]
            else:
                continue
            found.append(dict(metric=metric, pct=pct, value=cur, unit="", source=source, page=page_no, text=line))
    # sentence-based: join lines, split into sentences / bullet points
    joined = re.sub(r"\s*\n\s*", " ", text)
    if segment_page:
        return found   # sentences on segment pages describe divisions, not the group
    for sent in re.split(r"(?<=[.;])\s+(?=[A-Z])|\s[•▪■]\s", joined):
        if len(sent) > 400 or NOT_PCP.search(sent):
            continue
        for m in RE_SENT_C.finditer(sent):   # "$1,574 million ... up from $1,481 million"
            before = sent[max(0, m.start() - 90):m.start()]
            clause = re.split(r",\s(?:and|while|with)\s|;", before)[-1]
            metric = classify(clause, ticker)
            if not metric or is_segment(clause, ticker) or NOT_HEADLINE.search(m.group(0)):
                continue
            cur, prior = float(m.group("val").replace(",", "")), float(m.group("val2").replace(",", ""))
            if (m.group("unit") or "").lower()[:1] != (m.group("unit2") or "").lower()[:1] or prior <= 0:
                continue   # different units: can't compare safely
            found.append(dict(metric=metric, pct=round((cur / prior - 1) * 100, 1), value=cur,
                              unit=(m.group("cur") or "") + (m.group("unit") or ""), source="sentence_value",
                              page=page_no, text=sent[max(0, m.start() - 90):m.end()].strip()))
        for rx in (RE_SENT_A, RE_SENT_B, RE_SENT_D):
            for m in rx.finditer(sent):
                # the label is whatever metric is mentioned closest before the match
                before = sent[max(0, m.start() - 90):m.start()]
                clause = re.split(r",\s(?:and|while|with)\s|;|\band\b(?=[^%]*%)", before)[-1]
                metric = classify(clause, ticker)
                after = sent[m.end():m.end() + 25]
                if not metric or NOT_HEADLINE.search(m.group(0)) or is_segment(clause, ticker) \
                        or VS_2H.search(after) or (full_year and VS_1H.search(after)):
                    continue
                if ticker == "WBC" and not full_year and PRIOR_PERIOD.search(after):
                    continue
                val, unit = money(m)
                val_ok = val is not None and unit != ""
                found.append(dict(metric=metric, pct=signed(m.group("pct"), m.group("dir")),
                                  value=val if val_ok else None, unit=unit if val_ok else "",
                                  source="sentence_value" if val_ok else "sentence", page=page_no,
                                  text=sent[max(0, m.start() - 90):m.end() + 10].strip()))
    return found


def extract(path, ticker):
    rows = []
    with pdfplumber.open(path) as pdf:
        full_year = is_full_year(pdf)
        for i, page in enumerate(pdf.pages[:MAX_PAGES]):
            for text in page_texts(page):
                rows += candidates_from_text(text, i + 1, full_year, ticker)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.drop_duplicates(subset=["metric", "pct", "source", "page"])


def pick(cands):
    """Best candidate for one metric, with a confidence flag."""
    cands = cands.assign(trust=cands["source"].map(TRUST)).sort_values(["trust", "page"], ascending=[False, True])
    best = cands.iloc[0]
    top = cands[cands["trust"] == best["trust"]]
    level = best["trust"]
    conflict = bool((abs(top["pct"] - best["pct"]) > 0.5).any())
    if conflict:
        level = max(1, level - 1)
    return {"pct": best["pct"], "value": best["value"], "unit": best["unit"], "source": best["source"],
            "page": best["page"], "confidence": CONF[level], "conflict": conflict, "text": best["text"]}


METRICS = ["revenue", "npat_stat", "npat_underlying"]


def headlines(path, ticker=""):
    """Best figure per metric for one PDF (dict metric -> pick() result, or None), plus all candidates."""
    cands = extract(path, ticker)
    out = {}
    for metric in METRICS:
        sub = cands[cands["metric"] == metric] if not cands.empty else cands
        out[metric] = None if sub.empty else pick(sub)
    return out, cands


def headlines_from_text(text, ticker=""):
    """Same as headlines() but for pasted text (treated as one page)."""
    rows = candidates_from_text(text, 1, is_full_year_text(text[:6000]), ticker)
    cands = pd.DataFrame(rows)
    out = {}
    for metric in METRICS:
        sub = cands[cands["metric"] == metric] if not cands.empty else cands
        out[metric] = None if sub.empty else pick(sub)
    return out, cands


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out, allc = [], []
    # reuse earlier results unless --all is given
    done = set()
    if "--all" not in sys.argv and os.path.exists("headline_numbers.csv"):
        prev = pd.read_csv("headline_numbers.csv", encoding="utf-8-sig")
        out = prev.to_dict("records")
        done = set(prev["file"])
        if os.path.exists("headline_candidates.csv"):
            allc = [pd.read_csv("headline_candidates.csv", encoding="utf-8-sig")]
    for path in sorted(glob.glob(os.path.join(FOLDER, "*.pdf"))):
        fname = os.path.basename(path)
        if fname in done:
            continue
        ticker, date = fname[:-4].split("_")
        row = {"ticker": ticker, "date": date, "file": fname}
        try:
            best, cands = headlines(path, ticker)
        except Exception as e:
            print(f"{fname}: FAILED - {e}")
            best, cands = dict.fromkeys(METRICS), pd.DataFrame()
        if not cands.empty:
            allc.append(cands.assign(file=fname))
        for metric in METRICS:
            if best[metric] is None:
                row[f"{metric}_confidence"] = "none"
                continue
            for k, v in best[metric].items():
                row[f"{metric}_{k}"] = v
        out.append(row)
        print(fname, {m: row.get(f"{m}_pct") for m in ["revenue", "npat_stat", "npat_underlying"]})
    # utf-8-sig so Excel shows "–" properly instead of "â€“"
    pd.DataFrame(out).to_csv("headline_numbers.csv", index=False, encoding="utf-8-sig")
    if allc:
        pd.concat(allc).to_csv("headline_candidates.csv", index=False, encoding="utf-8-sig")
    print(f"Saved headline_numbers.csv ({len(out)} announcements)")


if __name__ == "__main__":
    main()
