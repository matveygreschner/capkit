"""Every financing product reduced to one dated cash-flow schedule.

Each builder returns a :class:`Schedule`: dated flows from the borrower's side (``+`` money received,
``-`` money paid) plus the facts needed to describe it. :func:`analyze` turns any schedule into the
same set of cost measures, which is what makes products comparable.

Products: merchant cash advance (fixed debit or split-percentage), revenue-based financing, term loan,
SBA 7(a), line of credit draw, invoice factoring, trade credit (early-payment discounts), equipment
lease.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

from . import apr as A
from . import params as P
from .calendar import add_months, business_days_after, parse

# Tax character tags (compare.py): how the cost is likely treated for federal income tax.
INTEREST, UNCERTAIN, RENT, PURCHASE = "interest", "character_uncertain", "rent", "purchase_cost"


@dataclass
class Schedule:
    product: str
    flows: List[A.Flow]
    unit: str
    amount: float                     # headline amount (advance, principal, face)
    net_proceeds: float               # cash actually received at funding
    tax_character: str
    terms: Dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def total_paid(self) -> float:
        return -sum(f.amount for f in self.flows if f.amount < 0)

    @property
    def total_received(self) -> float:
        return sum(f.amount for f in self.flows if f.amount > 0)

    @property
    def finance_charge(self) -> float:
        return self.total_paid - self.total_received

    def to_dict(self):
        return {"product": self.product, "amount": self.amount, "net_proceeds": round(self.net_proceeds, 2),
                "unit_period": self.unit, "tax_character": self.tax_character, "terms": self.terms,
                "notes": self.notes,
                "flows": [{"date": f.when.isoformat() if isinstance(f.when, date) else f.when,
                           "amount": round(f.amount, 2)} for f in self.flows]}


def _dates(start: date, n: int, frequency: str, holidays="frb") -> List[date]:
    if frequency == "business_day":
        return business_days_after(start, n, holidays)
    if frequency == "day":
        return [start + timedelta(k) for k in range(1, n + 1)]
    if frequency in ("week", "biweek"):
        step = 7 if frequency == "week" else 14
        return [start + timedelta(step * k) for k in range(1, n + 1)]
    if frequency == "month":
        return [add_months(start, k) for k in range(1, n + 1)]
    raise ValueError(f"unknown frequency {frequency!r}")


def _unit(frequency: str) -> str:
    return {"business_day": "day", "day": "day", "week": "week", "biweek": "biweek", "month": "month"}[frequency]


# ---------------------------------------------------------------- merchant cash advance

def mca_fixed(advance: float, factor_rate: float, payment: float, frequency: str = "business_day",
              funding_date="2027-01-04", fees: float = 0.0, holidays="frb") -> Schedule:
    """Merchant cash advance with a fixed debit (the common "daily ACH" structure).

    The purchased amount is ``advance * factor_rate``. Debits of ``payment`` start the first
    ``frequency`` period after funding and stop when the purchased amount is reached (the last debit
    may be partial). ``fees`` withheld at funding reduce the amount financed.
    """
    fd = parse(funding_date)
    owed = advance * factor_rate
    n = math.ceil(owed / payment - 1e-9)
    ds = _dates(fd, n, frequency, holidays)
    flows = [A.Flow(fd, advance - fees)]
    for d in ds:
        amt = min(payment, owed)
        flows.append(A.Flow(d, -amt))
        owed -= amt
    return Schedule("mca_fixed", flows, _unit(frequency), advance, advance - fees, UNCERTAIN,
                    {"factor_rate": factor_rate, "purchased_amount": advance * factor_rate, "payment": payment,
                     "frequency": frequency, "n_payments": n, "fees": fees},
                    ["An MCA is usually structured as a purchase of future receivables, not a loan. The APR "
                     "is a cost-comparison measure, as CA/NY require for sales-based financing."])


def mca_split(advance: float, factor_rate: float, holdback: float, sales: Sequence[float],
              frequency: str = "business_day", funding_date="2027-01-04", fees: float = 0.0,
              holidays="frb") -> Schedule:
    """Split-percentage MCA: each period the funder takes ``holdback`` x that period's card sales.

    ``sales`` is the per-period sales path (repeated cyclically if shorter than needed)."""
    fd = parse(funding_date)
    owed = advance * factor_rate
    if holdback * max(sales) <= 0:
        raise ValueError("holdback x sales must be positive")
    flows, k = [A.Flow(fd, advance - fees)], 0
    ds = _dates(fd, 20000, frequency, holidays) if frequency != "month" else _dates(fd, 600, frequency)
    while owed > 1e-9:
        amt = min(holdback * sales[k % len(sales)], owed)
        if amt > 0:
            flows.append(A.Flow(ds[k], -amt))
        owed -= amt
        k += 1
    return Schedule("mca_split", flows, _unit(frequency), advance, advance - fees, UNCERTAIN,
                    {"factor_rate": factor_rate, "holdback": holdback, "frequency": frequency, "periods": k,
                     "fees": fees}, ["Term and APR depend on the sales path; see stress results."])


def revenue_based(advance: float, cap_multiple: float, revenue_share: float, revenue: Sequence[float],
                  frequency: str = "month", funding_date="2027-01-04", fees: float = 0.0) -> Schedule:
    """Revenue-based financing: ``revenue_share`` of each period's revenue until ``cap_multiple`` x advance."""
    s = mca_split(advance, cap_multiple, revenue_share, revenue, frequency, funding_date, fees)
    s.product = "revenue_based"
    s.terms = {"cap_multiple": cap_multiple, "revenue_share": revenue_share, "frequency": frequency,
               "periods": s.terms["periods"], "fees": fees}
    return s


# ---------------------------------------------------------------- amortizing loans

def level_payment(principal: float, periodic_rate: float, n: int) -> float:
    if periodic_rate == 0:
        return principal / n
    return principal * periodic_rate / (1 - (1 + periodic_rate) ** -n)


def term_loan(amount: float, annual_rate: float, months: int, fee: float = 0.0,
              funding_date="2027-01-04", prepay_penalty: float = 0.0) -> Schedule:
    """Fully amortizing monthly loan. ``fee`` (dollars) is withheld from proceeds (a prepaid finance charge)."""
    fd = parse(funding_date)
    pmt = level_payment(amount, annual_rate / 12, months)
    flows = [A.Flow(fd, amount - fee)] + [A.Flow(add_months(fd, k), -pmt) for k in range(1, months + 1)]
    return Schedule("term_loan", flows, "month", amount, amount - fee, INTEREST,
                    {"annual_rate": annual_rate, "months": months, "payment": round(pmt, 2), "fee": fee,
                     "prepay_penalty": prepay_penalty})


def sba_7a(amount: float, prime: Optional[float] = None, spread: Optional[float] = None, months: int = 120,
           fee_rate: Optional[float] = None, fy: int = 2026, funding_date="2027-01-04",
           borrower_pays_fee: bool = True) -> Schedule:
    """SBA 7(a) variable-rate loan, rate held at today's Prime + spread for the schedule.

    ``spread`` defaults to the SOP 50 10 maximum for the loan size. The upfront guaranty fee is
    ``fee_rate`` x the *guaranteed portion* (85% at or below $150,000, 75% above), checked against the
    statutory ceiling."""
    prime = P.param("prime_rate") if prime is None else prime
    rate = P.sba_max_rate(amount, prime) if spread is None else prime + spread
    if spread is not None and prime + spread > P.sba_max_rate(amount, prime) + 1e-12:
        raise ValueError(f"spread {spread:.2%} exceeds the SOP 50 10 maximum for a ${amount:,.0f} loan")
    fee = P.sba_upfront_fee(amount, fy, fee_rate) if borrower_pays_fee else 0.0
    s = term_loan(amount, rate, months, fee, funding_date)
    s.product = "sba_7a"
    s.terms.update({"prime": prime, "spread": rate - prime, "guaranty_share": P.sba_guaranty_share(amount),
                    "upfront_fee": round(fee, 2)})
    s.notes.append("Variable rate held at today's Prime for the whole schedule; the APR changes if Prime moves.")
    return s


def loc_draw(draw: float, annual_rate: float, weeks: int, draw_fee: float = 0.0,
             funding_date="2027-01-04") -> Schedule:
    """One line-of-credit draw repaid after ``weeks``, interest paid weekly on the balance."""
    fd = parse(funding_date)
    i = annual_rate / 52
    flows = [A.Flow(fd, draw - draw_fee)] + [A.Flow(fd + timedelta(7 * k), -draw * i) for k in range(1, weeks + 1)]
    flows[-1] = A.Flow(flows[-1].when, flows[-1].amount - draw)
    return Schedule("line_of_credit", flows, "week", draw, draw - draw_fee, INTEREST,
                    {"annual_rate": annual_rate, "weeks": weeks, "draw_fee": draw_fee})


# ---------------------------------------------------------------- receivables and payables

def factoring(face: float, advance_rate: float, fee_per_30_days: float, days_to_pay: int,
              sale_date="2027-01-04", fee_basis: str = "per_30_or_part") -> Schedule:
    """Invoice factoring: an advance now, then the reserve less the fee when the customer pays the factor.

    The fee is ``fee_per_30_days`` x face for each 30 days (or part) the invoice is outstanding.
    The borrower's flows are +advance at sale and +rebate at collection, and the "payment" is the
    face value the factor collects (it never passes through the business), so the schedule is written
    as: +advance at sale, -(face - rebate) at collection."""
    sd = parse(sale_date)
    periods = math.ceil(days_to_pay / 30) if fee_basis == "per_30_or_part" else days_to_pay / 30
    fee = fee_per_30_days * face * periods
    adv = advance_rate * face
    rebate = face - adv - fee
    cd = sd + timedelta(days_to_pay)
    flows = [A.Flow(sd, adv), A.Flow(cd, -(adv + fee))]
    return Schedule("factoring", flows, "day", face, adv, UNCERTAIN,
                    {"advance_rate": advance_rate, "fee_per_30_days": fee_per_30_days, "days_to_pay": days_to_pay,
                     "fee": round(fee, 2), "rebate": round(rebate, 2)},
                    ["Cost depends on when the customer actually pays; late payment raises the fee."])


def trade_credit(invoice: float, discount: float, discount_days: int, net_days: int,
                 invoice_date="2027-01-04") -> Schedule:
    """Forgoing an early-payment discount is borrowing ``invoice*(1-discount)`` from the supplier for
    ``net_days - discount_days`` days and repaying ``invoice``."""
    d0 = parse(invoice_date)
    flows = [A.Flow(d0 + timedelta(discount_days), invoice * (1 - discount)),
             A.Flow(d0 + timedelta(net_days), -invoice)]
    s = Schedule("trade_credit", flows, "day", invoice, invoice * (1 - discount), PURCHASE,
                 {"discount": discount, "discount_days": discount_days, "net_days": net_days})
    return s


def early_pay_cost(discount: float, discount_days: int, net_days: int) -> dict:
    """Annualized cost of NOT taking an early-payment discount (e.g. 2/10 net 30)."""
    span = net_days - discount_days
    return {"nominal": discount / (1 - discount) * 365 / span,
            "effective": (1 + discount / (1 - discount)) ** (365 / span) - 1}


def equipment_lease(equipment_cost: float, payment: float, months: int, buyout: float = 0.0,
                    advance_payments: int = 0, fees: float = 0.0, start_date="2027-01-04") -> Schedule:
    """Lease treated as financing of ``equipment_cost``: payments (``advance_payments`` of them due at
    signing) plus the buyout (1 for a $1-out lease, the expected FMV/residual otherwise)."""
    d0 = parse(start_date)
    flows = [A.Flow(d0, equipment_cost - fees - payment * advance_payments)]
    remaining = months - advance_payments
    for k in range(1, remaining + 1):
        flows.append(A.Flow(add_months(d0, k), -payment))
    if buyout:
        last = flows[-1]
        flows[-1] = A.Flow(last.when, last.amount - buyout)
    return Schedule("equipment_lease", flows, "month", equipment_cost, equipment_cost, RENT,
                    {"payment": payment, "months": months, "buyout": buyout, "advance_payments": advance_payments,
                     "fees": fees}, ["Implicit rate; tax treatment depends on true-lease vs. conditional-sale."])


# ---------------------------------------------------------------- one set of measures for everything

def analyze(s: Schedule) -> dict:
    """APR (both Appendix J methods), EAR, XIRR, dollar cost and the naive annualized quote."""
    apr_a = A.apr_actuarial(s.flows, s.unit)
    apr_u = A.apr_us_rule(s.flows, s.unit)
    first = min(f.when for f in s.flows)
    last = max(f.when for f in s.flows)
    t, frac = A.period_position(first, last, s.unit)
    term_years = (t + frac) / A.UNITS[s.unit][0]
    out = {
        "product": s.product,
        "amount": s.amount,
        "net_proceeds": round(s.net_proceeds, 2),
        "total_paid": round(s.total_paid, 2),
        "finance_charge": round(s.finance_charge, 2),
        "apr_actuarial": apr_a,
        "apr_us_rule": apr_u,
        "unit_period": s.unit,
        "ear": A.ear(apr_a, s.unit),
        "xirr": A.xirr(s.flows),
        "term_days": (last - first).days,
        "simple_annualized": A.simple_annualized(s.total_received, s.total_paid, term_years),
        "cost_per_100_per_month": s.finance_charge / s.net_proceeds * 100 / max(term_years * 12, 1e-9),
        "tax_character": s.tax_character,
        "terms": s.terms,
        "notes": s.notes,
    }
    return out


BUILDERS = {
    "mca_fixed": mca_fixed, "mca_split": mca_split, "revenue_based": revenue_based, "term_loan": term_loan,
    "sba_7a": sba_7a, "line_of_credit": loc_draw, "factoring": factoring, "trade_credit": trade_credit,
    "equipment_lease": equipment_lease,
}


def build(spec: dict) -> Schedule:
    spec = dict(spec)
    kind = spec.pop("type")
    spec.pop("name", None)
    return BUILDERS[kind](**spec)
