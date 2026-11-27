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
from typing import Callable, Dict, List, Optional, Sequence, cast

from . import apr as A
from . import params as P
from .calendar import add_months, business_days_after, parse

# Tax character tags (compare.py): how the cost is likely treated for federal income tax.
INTEREST, UNCERTAIN, RENT, PURCHASE = "interest", "character_uncertain", "rent", "purchase_cost"
LEASE_UNKNOWN = "lease_character_unknown"   # lease with no buyout and no end_of_term


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


FREQUENCIES = ("business_day", "day", "week", "biweek", "month")


def _num(name, v, lo=None, hi=None, lo_open=False, integer=False):
    """Validate a numeric input: finite, in range. Bad inputs raise instead of producing a believable
    wrong number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{name} must be a finite number (got {v!r})")
    if integer and int(v) != v:
        raise ValueError(f"{name} must be a whole number (got {v!r})")
    if lo is not None and (v < lo or (lo_open and v == lo)):
        raise ValueError(f"{name} must be {'>' if lo_open else '>='} {lo} (got {v!r})")
    if hi is not None and v > hi:
        raise ValueError(f"{name} must be <= {hi} (got {v!r})")
    return v


def _freq(frequency):
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of {FREQUENCIES} (got {frequency!r})")
    return frequency


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
    _num("advance", advance, 0, lo_open=True)
    _num("factor_rate", factor_rate, 1.0, 10.0)
    _num("payment", payment, 0, lo_open=True)
    _num("fees", fees, 0, advance, )
    _freq(frequency)
    fd = parse(funding_date)
    owed = advance * factor_rate
    n = math.ceil(owed / payment - 1e-9)
    if n > MAX_PERIODS:
        raise ValueError(f"{n:,} debits are needed to repay this advance; the debit looks too small")
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


def _date_stream(start: date, frequency: str, holidays="frb"):
    """Payment dates after ``start``, generated lazily (no fixed-size array to overrun)."""
    if frequency not in ("business_day", "day", "week", "biweek", "month"):
        raise ValueError(f"unknown frequency {frequency!r}")
    k, d = 0, start
    while True:
        k += 1
        if frequency == "business_day":
            d = business_days_after(d, 1, holidays)[0]
            yield d
        elif frequency == "month":
            yield add_months(start, k)          # from the original date, so day 31 stays month-end
        else:
            yield start + timedelta(k * {"day": 1, "week": 7, "biweek": 14}[frequency])


MAX_PERIODS = 20_000      # about 80 years of business days: beyond this the advance is not being repaid


def mca_split(advance: float, factor_rate: float, holdback: float, sales: Sequence[float],
              frequency: str = "business_day", funding_date="2027-01-04", fees: float = 0.0,
              holidays="frb") -> Schedule:
    """Split-percentage MCA: each period the funder takes ``holdback`` x that period's card sales.

    ``sales`` is the per-period sales path (repeated cyclically if shorter than needed). Sales must be
    zero or positive; a path that never repays the purchased amount within ``MAX_PERIODS`` is an error."""
    _num("advance", advance, 0, lo_open=True)
    _num("factor_rate", factor_rate, 1.0, 10.0)
    _num("holdback", holdback, 0, 1, lo_open=True)
    _num("fees", fees, 0, advance)
    _freq(frequency)
    fd = parse(funding_date)
    owed = advance * factor_rate
    if not sales or any((not isinstance(x, (int, float))) or not math.isfinite(x) or x < 0 for x in sales):
        raise ValueError("sales must be a non-empty list of zero or positive amounts")
    if holdback <= 0 or holdback * max(sales) <= 0:
        raise ValueError("holdback x sales must be positive")
    flows, k = [A.Flow(fd, advance - fees)], 0
    dates = _date_stream(fd, frequency, holidays)
    while owed > 1e-9:
        if k >= MAX_PERIODS:
            raise ValueError("the sales path does not repay the purchased amount within "
                             f"{MAX_PERIODS} periods; check the holdback and sales")
        d = next(dates)
        amt = min(holdback * sales[k % len(sales)], owed)
        if amt > 0:
            flows.append(A.Flow(d, -amt))
        owed -= amt
        k += 1
    return Schedule("mca_split", flows, _unit(frequency), advance, advance - fees, UNCERTAIN,
                    {"factor_rate": factor_rate, "holdback": holdback, "frequency": frequency, "periods": k,
                     "fees": fees}, ["Term and APR depend on the sales path; see stress results."])


def revenue_based(advance: float, cap_multiple: float, revenue_share: float, revenue: Sequence[float],
                  frequency: str = "month", funding_date="2027-01-04", fees: float = 0.0) -> Schedule:
    """Revenue-based financing: ``revenue_share`` of each period's revenue until ``cap_multiple`` x advance."""
    _num("revenue_share", revenue_share, 0, 1, lo_open=True)
    s = mca_split(advance, cap_multiple, revenue_share, revenue, frequency, funding_date, fees)
    s.product = "revenue_based"
    s.terms = {"cap_multiple": cap_multiple, "revenue_share": revenue_share, "frequency": frequency,
               "periods": s.terms["periods"], "fees": fees}
    return s


# ---------------------------------------------------------------- amortizing loans

def level_payment(principal: float, periodic_rate: float, n: int) -> float:
    if periodic_rate == 0:
        return principal / n
    # 1 - (1+r)^-n computed without cancellation: exact for tiny r, never 0 for r > 0
    return principal * periodic_rate / -math.expm1(-n * math.log1p(periodic_rate))


def term_loan(amount: float, annual_rate: float, months: int, fee: float = 0.0,
              funding_date="2027-01-04", prepay_penalty: float = 0.0) -> Schedule:
    """Fully amortizing monthly loan. ``fee`` (dollars) is withheld from proceeds (a prepaid finance charge)."""
    _num("amount", amount, 0, lo_open=True)
    _num("annual_rate", annual_rate, 0, 5)
    _num("months", months, 1, 600, integer=True)
    _num("fee", fee, 0, amount)
    if fee >= amount:
        raise ValueError("fee must be less than the amount")
    fd = parse(funding_date)
    r = annual_rate / 12
    level = level_payment(amount, r, months)

    def last(pmt):
        bal = amount
        for _ in range(months - 1):
            bal = bal * (1 + r) - pmt
        return round(bal * (1 + r), 2)                       # the last payment clears the rounding residual
    pmt = math.floor(level * 100 + 0.5) / 100               # billed in cents, half up (as Excel ROUND)
    final = last(pmt)
    if final < 0:
        # Rounding up overpays; at high rates over long terms the excess compounds into a refund, which
        # no lender bills. Round down instead, so the final payment is slightly larger than the rest.
        pmt = math.floor(level * 100) / 100
        final = last(pmt)
        while final < 0 and pmt > 0:                         # guard against float noise at a cent
            pmt = round(pmt - 0.01, 2)
            final = last(pmt)
    pays = [pmt] * (months - 1) + [final]
    flows = [A.Flow(fd, amount - fee)] + [A.Flow(add_months(fd, k), -pays[k - 1]) for k in range(1, months + 1)]
    return Schedule("term_loan", flows, "month", amount, amount - fee, INTEREST,
                    {"annual_rate": annual_rate, "months": months, "payment": pmt, "final_payment": final,
                     "fee": fee, "prepay_penalty": prepay_penalty},
                    ["Payments are rounded to cents; the final payment absorbs the rounding difference."])


def sba_7a(amount: float, prime: Optional[float] = None, spread: Optional[float] = None, months: int = 120,
           fee_rate: Optional[float] = None, fy: Optional[int] = None, funding_date="2027-01-04",
           borrower_pays_fee: bool = True, zero_fee_eligible: bool = False, approval_date=None,
           program: str = "standard", prior_90_day_amount: float = 0.0, prior_90_day_fee: Optional[float] = None) -> Schedule:
    """SBA 7(a) variable-rate loan, rate held at today's Prime + spread for the schedule.

    ``spread`` defaults to the SOP 50 10 maximum for the loan size. The upfront guaranty fee is
    ``fee_rate`` x the *guaranteed portion* (85% at or below $150,000, 75% above), checked against the
    statutory ceiling. Loans approved within 90 days combine: give ``prior_90_day_amount`` and
    ``prior_90_day_fee`` (the fee already charged; 0 if none) together, as for ``sba_fee``."""
    if borrower_pays_fee:      # a lender-paid fee never reaches the borrower's cash flows
        prior_90_day_fee = P.resolve_prior_90_day_fee(prior_90_day_amount, prior_90_day_fee)
    prime_is_example = prime is None
    prime = P.param("prime_rate") if prime is None else prime
    rate = P.sba_max_rate(amount, prime) if spread is None else prime + spread
    if spread is not None and prime + spread > P.sba_max_rate(amount, prime) + 1e-12:
        raise ValueError(f"spread {spread:.2%} exceeds the SOP 50 10 maximum for a ${amount:,.0f} loan")
    if fy is None:
        fy = P.fiscal_year(parse(approval_date or funding_date))
    fee = P.sba_upfront_fee(amount, fy, fee_rate, months, zero_fee_eligible, program, prior_90_day_amount,
                            prior_90_day_fee) if borrower_pays_fee else 0.0
    s = term_loan(amount, rate, months, fee, funding_date)
    s.product = "sba_7a"
    s.terms.update({"prime": prime, "spread": rate - prime, "guaranty_share": P.sba_guaranty_share(amount + prior_90_day_amount),
                    "upfront_fee": round(fee, 2), "fiscal_year": fy})
    s.notes.append("Variable rate held at today's Prime for the whole schedule; the APR changes if Prime moves.")
    s.terms["program"] = program
    if approval_date is None and fy is not None:
        s.notes.append(f"Fee year FY{fy} was taken from the funding date; the SBA fee year follows the APPROVAL "
                       "date. Pass approval_date if the loan was approved in a different fiscal year.")
    if prime_is_example:
        s.notes.append(f"Prime was not given: {P.param('prime_rate'):.2%} is an EXAMPLE placeholder, not today's "
                       "rate. Pass the current Prime (FRED series DPRIME) for a real quote.")
    return s


def loc_draw(draw: float, annual_rate: float, weeks: int, draw_fee: float = 0.0,
             funding_date="2027-01-04") -> Schedule:
    """One line-of-credit draw repaid after ``weeks``, interest paid weekly on the balance."""
    _num("draw", draw, 0, lo_open=True)
    _num("annual_rate", annual_rate, 0, 5)
    _num("weeks", weeks, 1, 520, integer=True)
    _num("draw_fee", draw_fee, 0, draw)
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
    _num("face", face, 0, lo_open=True)
    _num("advance_rate", advance_rate, 0, 1, lo_open=True)
    _num("fee_per_30_days", fee_per_30_days, 0, 1)
    _num("days_to_pay", days_to_pay, 1, 3650, integer=True)
    if fee_basis not in ("per_30_or_part", "prorated"):
        raise ValueError("fee_basis must be 'per_30_or_part' or 'prorated'")
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
    _num("invoice", invoice, 0, lo_open=True)
    _num("discount", discount, 0, 1, lo_open=True)
    _num("discount_days", discount_days, 0, integer=True)
    _num("net_days", net_days, 1, integer=True)
    if discount_days >= net_days:
        raise ValueError("discount_days must be before net_days")
    d0 = parse(invoice_date)
    flows = [A.Flow(d0 + timedelta(discount_days), invoice * (1 - discount)),
             A.Flow(d0 + timedelta(net_days), -invoice)]
    s = Schedule("trade_credit", flows, "day", invoice, invoice * (1 - discount), PURCHASE,
                 {"discount": discount, "discount_days": discount_days, "net_days": net_days})
    return s


def early_pay_cost(discount: float, discount_days: int, net_days: int) -> dict:
    """Annualized cost of NOT taking an early-payment discount (e.g. 2/10 net 30)."""
    _num("discount", discount, 0, 1, lo_open=True)
    _num("discount_days", discount_days, 0, integer=True)
    _num("net_days", net_days, 1, integer=True)
    if discount_days >= net_days:
        raise ValueError("discount_days must be before net_days (e.g. 2/10 net 30: 10 < 30)")
    if discount >= 1:
        raise ValueError("discount must be below 100%")
    span = net_days - discount_days
    out: dict = {"nominal": discount / (1 - discount) * 365 / span}
    try:
        out["effective"] = (1 + discount / (1 - discount)) ** (365 / span) - 1
    except OverflowError:                      # e.g. 99/0 net 1: the compounded rate is not representable
        out["effective"] = None
        out["warning"] = "effective annual rate is too large to represent; the nominal rate is exact"
    return out


def equipment_lease(equipment_cost: float, payment: float, months: int, buyout: float = 0.0,
                    advance_payments: int = 0, fees: float = 0.0, start_date="2027-01-04",
                    end_of_term: str = "unspecified") -> Schedule:
    """Lease treated as financing of ``equipment_cost``: payments (``advance_payments`` of them due at
    signing) plus the buyout (1 for a $1-out lease, the expected FMV/residual otherwise). ``end_of_term`` =
    "return" (equipment goes back: rent), "own" (the business keeps it: conditional sale) or "unspecified"."""
    _num("equipment_cost", equipment_cost, 0, lo_open=True)
    _num("payment", payment, 0, lo_open=True)
    _num("months", months, 1, 600, integer=True)
    _num("advance_payments", advance_payments, 0, months - 1, integer=True)
    _num("buyout", buyout, 0)
    _num("fees", fees, 0)
    if equipment_cost - fees - payment * advance_payments <= 0:
        raise ValueError("fees and advance payments use up the whole equipment cost")
    d0 = parse(start_date)
    flows = [A.Flow(d0, equipment_cost - fees - payment * advance_payments)]
    remaining = months - advance_payments
    for k in range(1, remaining + 1):
        flows.append(A.Flow(add_months(d0, k), -payment))
    if buyout:
        last = flows[-1]
        flows[-1] = A.Flow(last.when, last.amount - buyout)
    if end_of_term not in ("return", "own", "unspecified"):
        raise ValueError("end_of_term must be 'return', 'own' or 'unspecified'")
    if end_of_term == "return" and buyout:
        raise ValueError("end_of_term 'return' means the equipment goes back, so there is no buyout: drop buyout "
                         "or use end_of_term 'own'")
    # $1-out / nominal buyout, or ownership at the end: likely a purchase (conditional sale). A return
    # lease with no buyout is a true lease. With no buyout and no end_of_term the character is unknown:
    # it is not labelled a purchase, and no after-tax figure is computed (compare.after_tax_cost).
    if end_of_term == "own" or 0 < buyout <= 0.01 * equipment_cost:
        character = "conditional_sale_likely"
    elif buyout == 0 and end_of_term == "unspecified":
        character = LEASE_UNKNOWN
    else:
        character = RENT
    return Schedule("equipment_lease", flows, "month", equipment_cost, flows[0].amount, character,
                    {"payment": payment, "months": months, "buyout": buyout, "advance_payments": advance_payments,
                     "fees": fees, "end_of_term": end_of_term},
                    ["Implicit rate; tax treatment depends on true-lease vs. conditional-sale."]
                    + (["No buyout and no end_of_term given: whether this is rent or a purchase is unknown. Pass "
                        "end_of_term='return' if the equipment goes back, 'own' if the business keeps it."]
                       if character == LEASE_UNKNOWN else []))


# ---------------------------------------------------------------- one set of measures for everything

def analyze(s: Schedule) -> dict:
    """APR (both Appendix J methods), EAR, XIRR, dollar cost and the naive annualized quote.

    A single advance repaid by a single payment (factoring, a forgone supplier discount) uses the term as
    the unit-period, as Appendix J requires. Measures that cannot be computed are returned as None with
    a warning instead of failing the whole analysis."""
    warnings = []
    pair = A._single_pair(s.flows)
    unit = s.unit
    if pair:
        apr_a = apr_u = A.apr_single_payment(pair[0].amount, -pair[1].amount, pair[0].when, pair[1].when)
        unit = "term"
        days = (pair[1].when - pair[0].when).days
        try:
            ear = (-pair[1].amount / pair[0].amount) ** (365 / days) - 1 if days else None
        except OverflowError:
            ear = None
            warnings.append("EAR is too large to represent (a very short, very expensive schedule).")
    else:
        apr_a = A.apr_actuarial(s.flows, unit)
        apr_u = A.apr_us_rule(s.flows, unit)
        ear = A.ear(apr_a, unit)
        n_roots = A.count_rates(s.flows, unit)
        if n_roots > 1:
            warnings.append(f"{n_roots} rates solve these cash flows; the smallest positive one is reported. "
                            "Check the schedule: alternating large inflows and outflows can do this.")
    if abs(apr_a - apr_u) > 0.00125:
        warnings.append("The actuarial and U.S. Rule APRs differ by more than 1/8 point; either may be "
                        "disclosed under Reg Z and CA/NY rules.")
    try:
        xirr = A.xirr(s.flows)
    except (ValueError, OverflowError):
        xirr = None
        warnings.append("XIRR is too large to compute (a very short, very expensive schedule).")
    when = [cast(date, f.when) for f in s.flows]
    first, last = min(when), max(when)
    term_days = (last - first).days
    if unit == "term":
        term_years = term_days / 365
    else:
        t, frac = A.period_position(first, last, unit)
        term_years = (t + frac) / A.UNITS[unit][0]
    out = {
        "product": s.product,
        "amount": s.amount,
        "net_proceeds": round(s.net_proceeds, 2),
        "total_paid": round(s.total_paid, 2),
        "finance_charge": round(s.finance_charge, 2),
        "apr_actuarial": apr_a,
        "apr_us_rule": apr_u,
        "unit_period": unit,
        "ear": ear,
        "xirr": xirr,
        "term_days": term_days,
        "simple_annualized": A.simple_annualized(s.total_received, s.total_paid, term_years),
        "cost_per_100_per_month": s.finance_charge / s.net_proceeds * 100 / max(term_years * 12, 1e-9),
        "tax_character": s.tax_character,
        "terms": s.terms,
        "notes": s.notes,
        "warnings": warnings,
    }
    return out


BUILDERS: Dict[str, Callable[..., Schedule]] = {
    "mca_fixed": mca_fixed, "mca_split": mca_split, "revenue_based": revenue_based, "term_loan": term_loan,
    "sba_7a": sba_7a, "line_of_credit": loc_draw, "factoring": factoring, "trade_credit": trade_credit,
    "equipment_lease": equipment_lease,
}


def build(spec: dict) -> Schedule:
    spec = dict(spec)
    kind = spec.pop("type", None)
    if kind not in BUILDERS:
        raise ValueError(f"offer type must be one of {sorted(BUILDERS)} (got {kind!r})")
    spec.pop("name", None)
    return BUILDERS[kind](**spec)
