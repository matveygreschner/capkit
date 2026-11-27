"""Every rate, limit and convention CapKit uses, each with its source and the date it was last checked.

This is the single source of truth, as in TaxKit: the engine, the workbook's ``Params_Sources`` sheet
and the skills' reference tables are all generated from it. ``status`` is ``"verified"`` when the value
was checked against the primary source on ``verified_on``, and ``"verify"`` when it is the best
available figure but must be re-checked against the named source before it is relied on.

A test (tests/test_params.py) fails when any entry is older than ``MAX_AGE_DAYS``, so stale law cannot
ship silently.
"""
from __future__ import annotations

from datetime import date

MAX_AGE_DAYS = 365

PARAMS = {
    # ---------------- Regulation Z, Appendix J ----------------
    "regz_tolerance_regular": {
        "value": 0.125, "unit": "percentage points",
        "desc": "APR accuracy tolerance for a regular transaction",
        "source": "12 CFR 1026.22(a)(2)", "verified_on": "2026-11-26", "status": "verified"},
    "regz_tolerance_irregular": {
        "value": 0.25, "unit": "percentage points",
        "desc": "APR accuracy tolerance for an irregular transaction (multiple advances, irregular "
                "payment periods or amounts, other than an irregular first period or first/final payment)",
        "source": "12 CFR 1026.22(a)(3)", "verified_on": "2026-11-26", "status": "verified"},
    "appj_days_per_month": {
        "value": 30, "unit": "days",
        "desc": "Days in a month when counting a fractional unit period (a month is 30 days; the "
                "alternative of 1/365 of a year is not used)",
        "source": "12 CFR 1026 Appendix J (b)(5)(iv)", "verified_on": "2026-11-26", "status": "verified"},

    # ---------------- State commercial financing disclosure laws ----------------
    "ca_cfdl_max_amount": {
        "value": 500_000, "unit": "USD",
        "desc": "California commercial financing disclosures apply to offers of $500,000 or less",
        "source": "Cal. Fin. Code 22800-22805; 10 CCR 900 et seq.", "verified_on": "2026-11-26",
        "status": "verify"},
    "ny_cfdl_max_amount": {
        "value": 2_500_000, "unit": "USD",
        "desc": "New York Commercial Finance Disclosure Law applies to offers of $2,500,000 or less",
        "source": "N.Y. Fin. Serv. Law 801-812; 23 NYCRR Part 600", "verified_on": "2026-11-26",
        "status": "verify"},
    "ca_apr_methods": {
        "value": ["actuarial", "us_rule"], "unit": "",
        "desc": "California allows the APR to be computed by either Appendix J method",
        "source": "10 CCR 940(a)", "verified_on": "2026-11-26", "status": "verified"},

    # ---------------- SBA 7(a) ----------------
    "sba_guaranty_share_small": {
        "value": 0.85, "unit": "share",
        "desc": "SBA guaranty share for 7(a) loans of $150,000 or less",
        "source": "15 U.S.C. 636(a)(2)", "verified_on": "2026-11-26", "status": "verify"},
    "sba_guaranty_share_large": {
        "value": 0.75, "unit": "share",
        "desc": "SBA guaranty share for 7(a) loans above $150,000",
        "source": "15 U.S.C. 636(a)(2)", "verified_on": "2026-11-26", "status": "verify"},
    "sba_fee_ceiling": {
        "value": [(150_000, 0.02), (700_000, 0.03), (float("inf"), 0.035)], "unit": "share of guaranteed portion",
        "desc": "Statutory ceiling on the upfront guaranty fee by loan amount (up to the bound), as a "
                "share of the guaranteed portion; plus 0.25% on guaranteed portion above $1,000,000",
        "source": "15 U.S.C. 636(a)(18)(A)", "verified_on": "2026-11-26", "status": "verify"},
    "sba_fee_ceiling_extra_over_1m": {
        "value": 0.0025, "unit": "share of guaranteed portion above $1,000,000",
        "desc": "Additional upfront fee ceiling on the part of the guaranteed portion above $1,000,000",
        "source": "15 U.S.C. 636(a)(18)(A)(iv)", "verified_on": "2026-11-26", "status": "verify"},
    "sba_fee_fy": {
        "value": {
            2026: {"short_term": 0.0025, "tiers": [(150_000, 0.02), (700_000, 0.03), (5_000_000, 0.035)],
                   "over_1m_guaranteed": 0.0375, "zero_fee_max": 950_000,
                   "zero_fee_who": "manufacturers (NAICS 31-33), not MARC loans"},
            2027: {"short_term": 0.0025, "tiers": [(150_000, 0.02), (700_000, 0.03), (5_000_000, 0.035)],
                   "over_1m_guaranteed": 0.0375, "zero_fee_max": 700_000,
                   "zero_fee_who": "manufacturers (NAICS 31-33), listed food-supply-chain NAICS codes, "
                                   "and businesses located in a rural area"},
        },
        "unit": "share of guaranteed portion",
        "desc": "Upfront guaranty fee by fiscal year (Oct 1 - Sep 30), on the guaranteed portion: 0.25% for "
                "maturities of 12 months or less; otherwise 2% (<= $150,000), 3% ($150,001-$700,000), 3.5% up to "
                "$1,000,000 guaranteed plus 3.75% above ($700,001-$5,000,000); 0% for eligible borrowers up to "
                "the zero-fee maximum. Two or more loans to one applicant within 90 days count as one loan",
        "source": "SBA Information Notice 5000-872051 (FY2026) and 5000-881797 (FY2027, effective Oct 1, 2026)",
        "verified_on": "2026-11-27", "status": "verified"},
    "sba_max_spread": {
        "value": [(50_000, 0.065), (250_000, 0.060), (350_000, 0.045), (float("inf"), 0.030)],
        "unit": "over Prime",
        "desc": "Maximum variable-rate spread over Prime by loan amount (up to the bound)",
        "source": "SBA SOP 50 10 8 (effective June 1, 2025), maximum allowable interest rates",
        "verified_on": "2026-11-26", "status": "verify"},

    # ---------------- Market rates (placeholders; live.py can fetch current values) ----------------
    "prime_rate": {
        "value": 0.07, "unit": "annual",
        "desc": "WSJ Prime Rate placeholder used in examples (fetch current: live.prime_rate())",
        "source": "FRED series DPRIME (Bank Prime Loan Rate)", "verified_on": "2026-11-26",
        "status": "placeholder"},
}


def param(key: str):
    return PARAMS[key]["value"]


def age_days(key: str, today: date | None = None) -> int:
    today = today or date.today()
    return (today - date.fromisoformat(PARAMS[key]["verified_on"])).days


def fiscal_year(d) -> int:
    """Federal fiscal year (FY2027 = Oct 1, 2026 - Sep 30, 2027)."""
    return d.year + 1 if d.month >= 10 else d.year


def _fee_table(fy: int) -> dict:
    table = PARAMS["sba_fee_fy"]["value"]
    if fy not in table:
        raise ValueError(f"SBA 7(a) fees for FY{fy} are not loaded; pass the fee rate from the SBA "
                         f"fiscal-year fee notice (fee_rate=...). Loaded years: {sorted(table)}")
    return table[fy]


def sba_fee_rate(amount: float, fy: int = 2026) -> float:
    """Long-term upfront fee rate on the guaranteed portion for the size tier of ``amount`` (the
    3.75% rate on guaranteed amounts above $1,000,000 is applied by :func:`sba_upfront_fee`)."""
    for bound, rate in _fee_table(fy)["tiers"]:
        if amount <= bound:
            return rate
    raise ValueError("SBA 7(a) loans are capped at $5,000,000")


def sba_guaranty_share(amount: float) -> float:
    return param("sba_guaranty_share_small") if amount <= 150_000 else param("sba_guaranty_share_large")


def sba_fee_ceiling(amount: float) -> float:
    """Statutory maximum upfront fee in dollars for a loan of ``amount``."""
    g = amount * sba_guaranty_share(amount)
    rate = next(r for b, r in param("sba_fee_ceiling") if amount <= b)
    return g * rate + max(0.0, g - 1_000_000) * param("sba_fee_ceiling_extra_over_1m")


# Working capital programs: upfront fee by maturity, on the guaranteed portion (FY2026 and FY2027 notices)
WCP_RATES = [(12, 0.0025), (24, 0.00525), (36, 0.0080), (48, 0.01075), (60, 0.0135)]
PROGRAMS = ("standard", "express_veteran", "ewcp", "wcp")


def _standard_fee(amount: float, fy: int, months, zero_fee_eligible: bool) -> float:
    g = sba_guaranty_share(amount) * amount
    t = _fee_table(fy)
    if zero_fee_eligible and amount <= t["zero_fee_max"]:
        return 0.0
    if months is not None and months <= 12:
        return t["short_term"] * g
    if amount <= 700_000:
        return sba_fee_rate(amount, fy) * g
    return 0.035 * min(g, 1_000_000) + t["over_1m_guaranteed"] * max(0.0, g - 1_000_000)


def sba_upfront_fee(amount: float, fy: int = 2026, rate: float | None = None, months: int | None = None,
                    zero_fee_eligible: bool = False, program: str = "standard",
                    prior_90_day_amount: float = 0.0, prior_90_day_fee: float = 0.0) -> float:
    """Upfront guaranty fee in dollars, on the *guaranteed portion* (never the face amount).

    * ``fy`` is the fiscal year of the loan's APPROVAL (FY2027 = approved Oct 1, 2026 - Sep 30, 2027).
    * ``months`` <= 12 uses the short-term rate. ``zero_fee_eligible`` applies the fiscal year's 0% tier
      (who qualifies is in the parameter table). ``program``: "standard", "express_veteran" (SBA Express
      to a veteran-owned business: $0), "ewcp" / "wcp" (rates by maturity).
    * Loans to the same applicant (and affiliates) approved within 90 days count as one loan: pass the
      earlier loans' total as ``prior_90_day_amount`` and the fee already charged as ``prior_90_day_fee``;
      this loan's fee is the combined fee less the fee already charged.
    * ``rate`` overrides the table (a share of the guaranteed portion, 0 to 1).
    Raises if the fee would exceed the statutory ceiling or the fiscal year is not loaded."""
    import math as _m
    for name, v in (("amount", amount), ("prior_90_day_amount", prior_90_day_amount),
                    ("prior_90_day_fee", prior_90_day_fee)):
        if not (isinstance(v, (int, float)) and _m.isfinite(v)) or v < 0:
            raise ValueError(f"{name} must be a finite, non-negative number")
    if program not in PROGRAMS:
        raise ValueError(f"program must be one of {PROGRAMS}")
    if months is not None and months <= 0:
        raise ValueError("months must be positive")
    if rate is not None and not (0 <= rate <= 1):
        raise ValueError("a fee rate override must be between 0 and 1 (a share of the guaranteed portion)")
    total = amount + prior_90_day_amount
    if amount <= 0 or total > 5_000_000:
        raise ValueError("SBA 7(a) loan amounts are $0 to $5,000,000 (90-day combined)")
    g = sba_guaranty_share(total) * amount
    if rate is not None:
        fee = rate * g
    elif program == "express_veteran":
        fee = 0.0
    elif program in ("ewcp", "wcp"):
        m = 12 if months is None else months
        if program == "ewcp" and m > 36:
            raise ValueError("EWCP fee rates in the notice cover maturities up to 36 months")
        r = next((r for mm, r in WCP_RATES if m <= mm), None)
        if r is None:
            raise ValueError("WCP fee rates in the notice cover maturities up to 60 months")
        fee = r * g
    elif prior_90_day_amount:
        fee = _standard_fee(total, fy, months, zero_fee_eligible) - prior_90_day_fee
        fee = max(fee, 0.0)
        g = sba_guaranty_share(total) * total
    else:
        fee = _standard_fee(amount, fy, months, zero_fee_eligible)
    ceiling = sba_fee_ceiling(total) - (prior_90_day_fee if prior_90_day_amount else 0.0)
    if fee > ceiling + 1e-9:
        raise ValueError(f"SBA upfront fee {fee:,.2f} exceeds the statutory ceiling "
                         f"{ceiling:,.2f} for a ${total:,.0f} loan (15 U.S.C. 636(a)(18)(A))")
    return fee


def sba_max_rate(amount: float, prime: float | None = None) -> float:
    prime = param("prime_rate") if prime is None else prime
    return prime + next(s for b, s in param("sba_max_spread") if amount <= b)
