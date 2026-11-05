"""Step 2.2-2.3: spin score and whether it predicts the share price reaction.

spin = tone that isn't explained by the profit change.
    1. profit_pct = underlying NPAT % change if we found one, else statutory.
    2. x = signed log of profit_pct, so +312% or -93% don't dominate the fit.
    3. Fit tone = a + b*x. Spin is the residual (actual tone minus predicted tone).
       pooled:      one line for all companies
       per company: compares each release with that company's own usual tone and profit
                    (subtract each company's averages first, then fit)
    4. Correlate spin with CAR (Pearson + Spearman, with p-values), plus robustness checks.

Outputs: spin_results.csv, spin_tests.csv, spin_scatter.png
"""
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------- 1. merge tone, CAR and profit numbers ----------
tone = pd.read_csv("tone_all.csv" if os.path.exists("tone_all.csv") else "tone_results.csv")
nums = pd.read_csv("headline_numbers.csv", encoding="utf-8-sig")
df = tone.merge(nums, on=["ticker", "date"], how="left")

use_under = df["npat_underlying_confidence"].fillna("none") != "none"
use_stat = df["npat_stat_confidence"].fillna("none") != "none"
df["profit_pct"] = np.where(use_under, df["npat_underlying_pct"], df["npat_stat_pct"])
df["profit_basis"] = np.where(use_under, "underlying", np.where(use_stat, "statutory", ""))
df["profit_confidence"] = np.where(use_under, df["npat_underlying_confidence"], df["npat_stat_confidence"])
df = df.dropna(subset=["profit_pct", "car", "tone_net"]).copy()
df["x"] = np.sign(df["profit_pct"]) * np.log1p(df["profit_pct"].abs())
print(f"{len(df)} announcements have tone, CAR and a profit change "
      f"({(df.profit_basis == 'underlying').sum()} underlying, {(df.profit_basis == 'statutory').sum()} statutory)")

# ---------- 2. spin ----------
# pooled
fit = stats.linregress(df["x"], df["tone_net"])
df["spin_pooled"] = df["tone_net"] - (fit.intercept + fit.slope * df["x"])
print(f"\nDo the numbers explain tone? (pooled)  slope = {fit.slope:.3f}, r = {fit.rvalue:.2f}, p = {fit.pvalue:.3f}")

# per company: demean within company, then fit (same as a regression with company dummies)
df = df[df.groupby("ticker")["ticker"].transform("size") >= 2].copy()
tone_d = df["tone_net"] - df.groupby("ticker")["tone_net"].transform("mean")
x_d = df["x"] - df.groupby("ticker")["x"].transform("mean")
b_fe = (x_d * tone_d).sum() / (x_d ** 2).sum()
df["spin_company"] = tone_d - b_fe * x_d
r_fe, p_fe = stats.pearsonr(x_d, tone_d)
print(f"Do the numbers explain tone? (within company)  slope = {b_fe:.3f}, r = {r_fe:.2f}, p = {p_fe:.3f}")


# ---------- 3. does spin predict CAR? ----------
def test(d, col, label):
    pr, pp = stats.pearsonr(d[col], d["car_pct"])
    sr, sp = stats.spearmanr(d[col], d["car_pct"])
    return {"test": label, "measure": col, "n": len(d), "pearson_r": pr, "pearson_p": pp,
            "spearman_r": sr, "spearman_p": sp}


lo, hi = df["car_pct"].quantile([0.05, 0.95])
trimmed = df[df["car_pct"].between(lo, hi)]
trusted = df[df["profit_confidence"].isin(["high", "medium"])]
rows = []
for col in ["spin_pooled", "spin_company"]:
    rows += [test(df, col, "all"),
             test(trimmed, col, "drop top/bottom 5% CAR"),
             test(trusted, col, "high/medium confidence only")]
# benchmarks: do tone alone or profit alone predict CAR in this same sample?
rows += [test(df, "tone_net", "benchmark: tone alone"), test(df, "x", "benchmark: profit change alone")]
res = pd.DataFrame(rows)
print("\nSpin vs CAR (%):")
print(res.round(3).to_string(index=False))

df.to_csv("spin_results.csv", index=False, encoding="utf-8-sig")
res.to_csv("spin_tests.csv", index=False, encoding="utf-8-sig")

# ---------- data for the website ----------
# spin line (pooled) + every scored release, so the site can say "more upbeat than X% of releases"
os.makedirs("data", exist_ok=True)
with open("data/spin_model.json", "w") as f:
    json.dump({"intercept": fit.intercept, "slope": fit.slope, "transform": "signed_log",
               "n": int(len(df)), "built_from": "tone_all.csv + headline_numbers.csv"}, f, indent=2)
bench = tone[["ticker", "date", "tone_net"]].merge(
    df[["ticker", "date", "profit_pct", "profit_basis", "spin_pooled"]], on=["ticker", "date"], how="left")
bench.to_csv("data/benchmark.csv", index=False)
print(f"Saved data/spin_model.json and data/benchmark.csv ({len(bench)} releases, {bench.spin_pooled.notna().sum()} with spin)")

# ---------- 4. chart ----------
BLUE, INK, INK2, GRID, SURFACE = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True, facecolor=SURFACE)
for ax, col, title in [(axes[0], "spin_pooled", "Pooled spin"), (axes[1], "spin_company", "Spin vs company's own norm")]:
    ax.set_facecolor(SURFACE)
    ax.scatter(df[col], df["car_pct"], s=40, color=BLUE, alpha=0.8, edgecolor=SURFACE, linewidth=1.5, zorder=3)
    slope, intercept = np.polyfit(df[col], df["car_pct"], 1)
    xs = np.linspace(df[col].min(), df[col].max(), 50)
    ax.plot(xs, slope * xs + intercept, color=INK2, linestyle="--", linewidth=1.5, zorder=2)
    r = res[(res.measure == col) & (res.test == "all")].iloc[0]
    ax.set_title(f"{title}\nr = {r.pearson_r:.2f}, p = {r.pearson_p:.2f}  (n = {int(r.n)})", color=INK, fontsize=11, loc="left")
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.axvline(0, color=GRID, linewidth=0.8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=INK2)
    ax.set_xlabel("Spin (tone above what the profit change predicts)", color=INK2)
    # label the most extreme points only
    for _, p in df.loc[(df[col].abs().rank(ascending=False) <= 3) | (df["car_pct"].abs().rank(ascending=False) <= 3)].iterrows():
        ax.annotate(f"{p.ticker} {p.date[2:7]}", (p[col], p["car_pct"]), xytext=(4, 4),
                    textcoords="offset points", fontsize=8, color=INK2)
axes[0].set_ylabel("Abnormal return, days -1 to +1 (%)", color=INK2)
fig.suptitle("Does spin predict the share price reaction?", color=INK, fontsize=13, x=0.01, ha="left")
fig.tight_layout()
fig.savefig("spin_scatter.png", dpi=150, facecolor=SURFACE)
print("\nSaved spin_results.csv, spin_tests.csv, spin_scatter.png")
