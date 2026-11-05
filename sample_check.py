"""Pick a random sample of extracted numbers for checking by hand.

Writes hand_check_sample.csv: open each PDF at the page shown, compare the number,
and fill in the 'correct' column (y / n / note).
"""
import sys
import pandas as pd

N_PER_LEVEL = 7
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
d = pd.read_csv("headline_numbers.csv", encoding="utf-8-sig")
if "--new" in sys.argv:   # only releases added after Step 1 (not in tone_results.csv)
    step1 = pd.read_csv("tone_results.csv")
    d = d[~d["file"].isin(step1["ticker"] + "_" + step1["date"] + ".pdf")]
    N_PER_LEVEL = 10
parts = []
for m in ["revenue", "npat_stat", "npat_underlying"]:
    s = d[d[f"{m}_confidence"] != "none"][["file", f"{m}_pct", f"{m}_confidence", f"{m}_source", f"{m}_page", f"{m}_text"]]
    s.columns = ["file", "pct", "confidence", "source", "page", "text"]
    parts.append(s.assign(metric=m))
allrows = pd.concat(parts)
sample = pd.concat(g.sample(min(len(g), N_PER_LEVEL), random_state=1)
                   for _, g in allrows.groupby("confidence"))
sample["correct"] = ""
out = "hand_check_sample_new.csv" if "--new" in sys.argv else "hand_check_sample.csv"
sample.to_csv(out, index=False, encoding="utf-8-sig")
print("Saved", out)
for _, r in sample.iterrows():
    print(f"{r.confidence:6} {r.file[:-4]:15} {r.metric:16} {r.pct:+7.1f}  [{r.source} p{r.page}] {str(r.text)[:140]}")
