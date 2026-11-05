"""Regression tests for extract_headlines.py: real lines from announcements and the answer each should give.
Run after changing any extraction rule:  python test_extract.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import extract_headlines as e

# (ticker, full_year, text, expected)
tests = [
    ("MPL", True, "Group revenue from external customers 7,807.0 8,175.8 4.7%", "revenue +4.7"),
    ("MPL", False, "NPAT attributable to Medibank shareholders 343.2 340.3 (0.8%)", "npat_stat -0.8"),
    ("MIN", True, "Reported NPAT was $1.2B, with Underlying NPAT of $822M, up 831% pcp.", "npat_underlying +831"),
    ("IAG", True, "Net profit was driven by an 8% rise in net earned premium.", "nothing"),
    ("CBA", False, "Cash NPAT of $5,153 million was 9% higher reflecting volume growth.", "npat_underlying +9"),
    ("BSL", True, "reported FY2026 net profit after tax (NPAT) of $802 million, a 857 per cent increase on FY2025.", "npat_stat +857"),
    ("WDS", False, "net profit after tax (NPAT) of $2,718 million (24% lower from 2024) and", "npat_stat -24"),
    ("IAG", False, "Cash earnings 176 223 26.7%", "npat_underlying +26.7"),
    ("TLS", True, "Profit for the year 1,788 2,051 (263) (12.8)", "npat_stat -12.8"),
    ("COL", True, "Profit from continuing operations, excl. significant items - reported 1,104 1,128 (2.1%) 3.7%", "npat_underlying -2.1"),
    ("WBC", False, "Net operating income 9,959 10,239 10,799 (3) (8)", "revenue -7.8"),
    ("XRO", True, "Operating revenue ($000s) 2,753,081 2,102,652 31%", "revenue +30.9"),
    ("ORG", True, "Statutory profit of $1,574 million for FY26, up from $1,481 million in FY25.", "npat_stat +6.3"),
    ("WES", False, "Net profit after tax 1,467 1,425 2.9", "npat_stat +2.9"),
    # IAG FY22: columns are FY21, FY22 and direction is an arrow image, so the % has no sign (hand-check round 2)
    ("IAG", True, "Cash earnings 747 213 71.5%", "npat_underlying -71.5"),
    ("IAG", True, "GWP 12,602 13,317 5.7%", "nothing"),   # GWP isn't one of our metrics
    ("IAG", True, "NEP 7,473 7,909 5.8%", "nothing"),
    ("SHL", False, "Net Profit 202 382 47%", "npat_stat -47.1"),   # unsigned fall, current year first
    # SHL FY25: a division's organic growth, not the group's reported revenue (hand-check round 2)
    ("SHL", True, "Sonic's Radiology division performed very strongly during the year, achieving organic revenue growth of 10% and EBITDA growth", "nothing"),
    # BSL 1H26: half-year release; "on 1H FY2025" is the pcp, not a half-on-half comparison
    ("BSL", False, "BlueScope today reported 1H FY2026 net profit after tax (NPAT) of $391 million, a 118 per cent increase on 1H FY2025.", "npat_stat +118"),
]

# half-year vs full-year guess (decides whether "on 1H.." comparisons are kept)
for text, want in [("BlueScope 1H FY2026 Results. Half Year Results. 1H FY2026 net profit. Appendix 4D. annual report", False),
                   ("FY2026 Results. Full year net profit. Appendix 4E.", True),
                   ("HY25 results. Interim dividend. Six months ended 31 December.", False)]:
    got = e.is_full_year_text(text)
    print(f"{'OK  ' if got == want else 'FAIL'} full_year guess: got {got} want {want} | {text[:50]}")
for t, fy, s, want in tests:
    c = e.candidates_from_text(s, 1, fy, t)
    got = ", ".join(f"{x['metric']} {x['pct']:+g}" for x in c) or "nothing"
    print(f"{'OK  ' if want in got or got == want else 'FAIL'} {t}: got [{got}] want [{want}]")

