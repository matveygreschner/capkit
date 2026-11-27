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
        "value": {2026: [(150_000, 0.02), (700_000, 0.03), (5_000_000, 0.035)]}, "unit": "share of guaranteed portion",
        "desc": "Fiscal-year upfront guaranty fee rates actually charged (can be below the ceiling, "
                "including 0% in some years). Placeholder = statutory levels; confirm against the FY notice",
        "source": "SBA 7(a) fiscal-year fee notice (Federal Register / SBA Information Notice)",
        "verified_on": "2026-11-26", "status": "verify"},
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


def sba_fee_rate(amount: float, fy: int = 2026) -> float:
    """Upfront guaranty fee as a share of the *guaranteed portion* for a loan of ``amount``."""
    for bound, rate in PARAMS["sba_fee_fy"]["value"][fy]:
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


def sba_upfront_fee(amount: float, fy: int = 2026, rate: float | None = None) -> float:
    """Upfront guaranty fee in dollars: rate x guaranteed portion (NOT x face amount).

    ``rate`` overrides the fiscal-year table. Raises if the fee would exceed the statutory ceiling."""
    r = sba_fee_rate(amount, fy) if rate is None else rate
    fee = r * sba_guaranty_share(amount) * amount
    if fee > sba_fee_ceiling(amount) + 1e-9:
        raise ValueError(f"SBA upfront fee {fee:,.2f} exceeds the statutory ceiling "
                         f"{sba_fee_ceiling(amount):,.2f} for a ${amount:,.0f} loan (15 U.S.C. 636(a)(18)(A))")
    return fee


def sba_max_rate(amount: float, prime: float | None = None) -> float:
    prime = param("prime_rate") if prime is None else prime
    return prime + next(s for b, s in param("sba_max_spread") if amount <= b)
