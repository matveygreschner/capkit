"""Independent plan evaluator (stdlib): re-price any funding plan from product definitions.

It does NOT read the optimizer's matrix. Every cash flow is rebuilt from the offer terms: the merchant
cash advance debit by debit until the purchased amount is collected, the amortizing loans from their
level payment and due dates, the invoices from their discount and net weeks, the factoring advance,
fee and rebate from the sale and collection weeks. It then walks the cash balance week by week.

Uses:
* the oracle for the optimizer (its objective and weekly cash must match this to 1e-6);
* the ``Mix_Evaluator`` logic behind the skill's no-scipy fallback: a user can propose a mix and see
  whether it is feasible and what it is worth;
* the exploit check: a plan that prepays before funding is rejected.
"""
from __future__ import annotations

import math
from typing import Dict, List

from ..optimize.model import _series, expand_offers, invoices
from ..products import level_payment


class InvalidPlan(ValueError):
    pass


def _offer_for(offers, name, amount):
    exact = [o for o in offers if o["name"] == name]
    if exact:
        return exact[0]
    tiers = [o for o in offers if o.get("group") == name and o["min"] - 1e-6 <= amount <= o["max"] + 1e-6]
    if not tiers:
        raise InvalidPlan(f"no offer or tier named {name!r} can carry ${amount:,.2f}")
    return tiers[0]


def _mca_flows(o, amount, s, u, T):
    """Debit by debit. Returns (debits by week, prepayment by week, payoff value open at T)."""
    owed = o["factor_rate"] * amount
    per = o["weekly_debit_per_dollar"] * amount
    deb, pre = {}, {}
    for t in range(s + 1, T + 1):
        d = min(per, owed)
        if d > 0:
            deb[t] = d
            owed -= d
        if u is not None and t == u:
            pre[t] = (1 - o.get("payoff_discount", 0.0)) * (1 + o.get("prepay_penalty", 0.0)) * owed
            owed = 0.0
            break
    return deb, pre, owed if u is None else 0.0


def _loan_flows(o, amount, s, u, T):
    rate, months = o["annual_rate"], o["months"]
    pmt = level_payment(amount, rate / 12, months)
    bal, last_due = amount, 0.0
    deb, pre = {}, {}
    for mth in range(1, months + 1):
        due = mth * 52 / 12
        wk = s + math.ceil(due - 1e-12)
        if wk > T or (u is not None and wk > u):
            break
        deb[wk] = deb.get(wk, 0.0) + pmt
        bal = bal * (1 + rate / 12) - pmt
        last_due = due
    end = u if u is not None else T
    payoff = max(bal, 0.0) * (1 + rate / 52 * ((end - s) - last_due))
    if u is not None:
        pre[u] = payoff * (1 + o.get("prepay_penalty", 0.0))
        return deb, pre, 0.0
    return deb, pre, payoff


def evaluate(scenario: dict, plan: dict, H: float = 0.0, tol: float = 1e-6) -> dict:
    """Weekly cash and terminal net position of ``plan``; ``feasible`` False lists every violated rule."""
    sc = scenario
    T = int(sc["horizon_weeks"])
    floor = _series(sc.get("cash_floor", 0.0), T)
    R = _series(sc.get("revenue", 0.0), T)
    c = _series(sc["operating_cash_flow"], T)
    alpha = sc.get("affordability_share", 1.0)
    idep = sc.get("deposit_rate", 0.0) / 52
    loc = sc.get("line_of_credit") or {}
    iL = loc.get("annual_rate", 0.0) / 52
    offers = expand_offers(sc)
    inv = invoices(sc)
    fac = sc.get("factoring") or {}
    recv = fac.get("receivables", [])
    problems: List[str] = []

    inflow = [0.0] * (T + 1)
    debits = [0.0] * (T + 1)
    prepay = [0.0] * (T + 1)
    open_liab = 0.0
    taken: Dict[str, int] = {}
    for f in plan.get("fundings", []):
        amt, s = float(f["amount"]), int(f["week"])
        u = f.get("prepay_week")
        u = int(u) if u is not None else None
        o = _offer_for(offers, f["offer"], amt)
        grp = o.get("group", o["name"])
        taken[grp] = taken.get(grp, 0) + 1
        a, b = o.get("weeks", [1, T])
        if not (a <= s <= b) or s < 1 or s > T:
            problems.append(f"{o['name']}: week {s} is outside its availability {a}-{b}")
        if not (o.get("min", 0) - tol <= amt <= o["max"] + tol):
            problems.append(f"{o['name']}: ${amt:,.2f} outside its ${o.get('min', 0):,.0f}-${o['max']:,.0f} range")
        if u is not None and (u <= s or u > T):
            problems.append(f"{o['name']}: prepayment in week {u} is not after funding week {s}")
            continue
        if u is not None and not o.get("prepayable", True):
            problems.append(f"{o['name']}: not prepayable")
        fee = o.get("fee_share", o.get("fee", 0.0))
        inflow[s] += (1 - fee) * amt
        if o["type"] == "mca":
            deb, pre, owed = _mca_flows(o, amt, s, u, T)
            r_week = 0.0
        else:
            deb, pre, owed = _loan_flows(o, amt, s, u, T)
            r_week = o["annual_rate"] / 52
        for t, v in deb.items():
            debits[t] += v
        for t, v in pre.items():
            prepay[t] += v
        open_liab += owed * (1 + r_week * H)
    for g, n in taken.items():
        if n > 1:
            problems.append(f"{g}: taken {n} times (at most once)")

    bal = plan.get("loc_balance") or [0.0] * T
    bal = [loc.get("balance", 0.0)] + [float(v) for v in bal]
    e = {int(k): float(v) for k, v in (plan.get("early_pay") or {}).items()}
    for n, v in e.items():
        if not (-tol <= v <= 1 + tol):
            problems.append(f"invoice {n}: early-pay share {v} must be between 0 and 1")
        elif not (0 <= n < len(inv)) or inv[n]["discount_week"] > T or inv[n].get("discount", 0) <= 0:
            problems.append(f"invoice {n}: no early-payment discount is available inside the horizon")
    ysales = [(int(y["receivable"]), int(y["week"]), float(y["share"])) for y in plan.get("factoring", [])]
    sold = {}
    for n, q, sh in ysales:
        if not (-tol <= sh <= 1 + tol):
            problems.append(f"receivable {n}: share sold {sh} must be between 0 and 1")
        sold[n] = sold.get(n, 0.0) + sh
        r = recv[n]
        if not (r["issue_week"] <= q < r["collect_week"]):
            problems.append(f"receivable {n}: sold in week {q}, outside {r['issue_week']}..{r['collect_week'] - 1}")
        if not r.get("eligible", True):
            problems.append(f"receivable {n}: not eligible for factoring")
    for n, v in sold.items():
        if v > 1 + tol:
            problems.append(f"receivable {n}: sold {v:.0%} (> 100%)")

    def fee_rate(n, q):
        days = (recv[n]["collect_week"] - q) * 7
        return fac["fee_per_30_days"] * math.ceil(days / 30 - 1e-12)

    aF = fac.get("advance_rate", 0.0)
    B = [float(sc["starting_cash"])] + [0.0] * T
    weeks = []
    for t in range(1, T + 1):
        d_loc = bal[t] - bal[t - 1]
        if bal[t] < -tol or (loc and bal[t] > loc["limit"] + tol) or (not loc and abs(bal[t]) > tol):
            problems.append(f"week {t}: LOC balance {bal[t]:,.2f} outside 0..limit")
        interest = iL * bal[t - 1]
        inv_cash = 0.0
        for n, i in enumerate(inv):
            if i["discount_week"] == t and n in e:
                inv_cash -= (1 - i["discount"]) * i["amount"] * e[n]
            if i["net_week"] == t:
                inv_cash -= i["amount"] * (1 - e.get(n, 0.0))
        fac_cash = sum(aF * recv[n]["face"] * sh for n, q, sh in ysales if q == t)
        for n, r in enumerate(recv):
            if r["collect_week"] == t:
                fac_cash += r["face"] * (1 - sold.get(n, 0.0))
                fac_cash += sum((1 - aF - fee_rate(n, q)) * r["face"] * sh for n2, q, sh in ysales if n2 == n)
        draw_fee = loc.get("draw_fee", 0.0) * max(d_loc, 0.0)
        B[t] = ((1 + idep) * B[t - 1] + c[t] + inflow[t] - debits[t] - prepay[t] + d_loc - draw_fee
                - interest + inv_cash + fac_cash)
        if floor[t] is not None and B[t] < floor[t] - tol:
            problems.append(f"week {t}: cash {B[t]:,.2f} below the floor {floor[t]:,.2f}")
        if R[t] is not None and (alpha < 1.0 or sc.get("revenue") is not None) \
                and debits[t] + interest > alpha * R[t] + tol:
            problems.append(f"week {t}: debits {debits[t] + interest:,.2f} exceed {alpha:.0%} of revenue")
        if fac:
            out = sum(aF * recv[n]["face"] * sh for n, q, sh in ysales if q <= t < recv[n]["collect_week"])
            if out > fac.get("limit", math.inf) + tol:
                problems.append(f"week {t}: factoring advances {out:,.2f} exceed the facility limit")
        weeks.append({"week": t, "operating": c[t], "funding_in": round(inflow[t], 2),
                      "scheduled_debits": round(debits[t], 2), "prepayments": round(prepay[t], 2),
                      "loc_change": round(d_loc, 2), "loc_interest": round(interest, 2),
                      "loc_balance": round(bal[t], 2), "invoices_paid": round(-inv_cash, 2),
                      "factoring_cash": round(fac_cash, 2), "cash": round(B[t], 2)})

    dscr = sc.get("dscr")
    if dscr:
        service = sum(debits[1:]) + sum(iL * bal[t - 1] for t in range(1, T + 1))
        if service > dscr["ebitda"] / dscr["min"] + tol:
            problems.append(f"debt service {service:,.2f} exceeds EBITDA / DSCR minimum "
                            f"({dscr['ebitda'] / dscr['min']:,.2f})")
    terminal = (1 + idep * H) * B[T] - (1 + iL * H) * bal[T] - open_liab
    for n, i in enumerate(inv):
        if i["net_week"] > T:
            terminal -= i["amount"] * (1 - e.get(n, 0.0))
    for n, r in enumerate(recv):
        if r["collect_week"] > T:
            terminal += r["face"] * (1 - sold.get(n, 0.0))
            terminal += sum((1 - aF - fee_rate(n, q)) * r["face"] * sh for n2, q, sh in ysales if n2 == n)
    return {"feasible": not problems, "problems": problems, "terminal_net_position": terminal,
            "open_liabilities_at_T": round(open_liab, 2), "weeks": weeks, "H": H}
