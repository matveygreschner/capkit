"""Funding-mix model: which money to take, how much, in which week, and whether to prepay it.

Stdlib only. :func:`build_model` turns a scenario (JSON-like dict) into a solver-neutral mixed-integer
linear program; :mod:`capkit.optimize.solve` hands it to HiGHS. All the finance lives here.

Formulation (weeks t = 1..T, week 0 = today):

* Lump-sum offers j (merchant cash advance, term loan, SBA 7(a) tier) use *disaggregated* variables
  ``x[j,s,u]`` = dollars of offer j funded in week s and prepaid in full in week u (u = NEVER: not
  prepaid inside the horizon), with a binary ``z[j,s,u]``. Every debit, prepayment and terminal payoff
  is then a fixed coefficient times one x, and "prepay before funding" cannot be expressed (u > s by
  construction). Offers in the same group (e.g. SBA spread tiers) are mutually exclusive.
* Line of credit: draw d_t, repay p_t, balance b_t <= limit, interest on b_{t-1} paid weekly.
* Supplier invoices: e_i in [0, 1] = share paid early (in its discount week) to take the discount.
* Factoring facility: y[r,q] in [0, 1] = share of receivable r sold in week q (before collection).
* Cash: B_t = (1 + i_dep) B_{t-1} + c_t + inflows - outflows, B_t >= floor_t.
* Affordability: scheduled debits + LOC interest <= alpha x revenue_t every week.
* Optional debt-service coverage over the horizon.

Objective: maximize terminal net position = cash at T minus every liability still open at T at its
payoff value, plus receivables still to collect, minus invoices still to pay. With a post-horizon carry
of H weeks each open balance also accrues H weeks at its own contract rate (and cash at i_dep). There is
deliberately no hurdle/discount rate: idle borrowed cash earns only i_dep, so the model borrows only what
the cash floor needs or what pays for itself.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from .. import params as P

NEVER = "never"


# ---------------------------------------------------------------- offer profiles

def mca_profile(o: dict, T: int):
    """Per-dollar weekly debit k(tau) and payoff value rho(tau) after the week-tau debit."""
    factor, k = o["factor_rate"], o["weekly_debit_per_dollar"]
    n = math.ceil(factor / k - 1e-12)
    kk, rho, owed = {}, {0: factor}, factor
    for tau in range(1, T + 1):
        d = min(k, max(owed, 0.0)) if tau <= n else 0.0
        if d:
            kk[tau] = d
        owed -= d
        rho[tau] = max(owed, 0.0)
    return kk, rho, 0.0


def amortizing_profile(annual_rate: float, months: int, T: int):
    """Monthly level payments; payment m falls in week ceil(m*52/12) after funding.

    Payoff value after week tau = remaining principal x (1 + simple interest at the annual rate for
    the weeks since the last *contractual* due date m*52/12)."""
    im = annual_rate / 12
    pf = im / (1 - (1 + im) ** -months) if im else 1 / months
    due = [(m * 52 / 12, math.ceil(m * 52 / 12 - 1e-12)) for m in range(1, months + 1)]
    kk: Dict[int, float] = {}
    for _, wk in due:
        if wk <= T:
            kk[wk] = kk.get(wk, 0.0) + pf
    rho = {}
    for tau in range(0, T + 1):
        bal, last = 1.0, 0.0
        for cd, wk in due:
            if wk <= tau:
                bal = bal * (1 + im) - pf
                last = cd
        rho[tau] = max(bal, 0.0) * (1 + annual_rate / 52 * (tau - last))
    return kk, rho, annual_rate / 52


def sba_tiers(o: dict) -> List[dict]:
    """Split an SBA 7(a) offer into one offer per (spread tier x fee tier) band, so that the rate and
    fee are fixed per dollar inside each band (keeps the model linear)."""
    prime = o.get("prime", P.param("prime_rate"))
    lo, hi = o.get("min", 25_000), o["max"]
    fy = o.get("fy", 2026)
    bounds = sorted(({b for b, _ in P.param("sba_max_spread")} | {b for b, _ in P.param("sba_fee_fy")[fy]}
                     | {150_000}) - {math.inf})
    edges, cur = [], lo
    for b in bounds:
        if b >= hi:
            break
        if b >= cur:
            edges.append((cur, b))
            cur = b + 1
    edges.append((cur, hi))
    tiers = []
    for k, (a, b) in enumerate(edges, 1):
        rate = o.get("rate") or P.sba_max_rate(b, prime)
        if "spread" in o:
            rate = prime + o["spread"]
        fee_rate = o.get("fee_rate_of_guaranteed")
        fee_share = (P.sba_fee_rate(b, fy) if fee_rate is None else fee_rate) * P.sba_guaranty_share(b)
        if P.sba_fee_ceiling(b) + 1e-9 < fee_share * b:
            raise ValueError(f"SBA fee {fee_share:.4%} of face exceeds the statutory ceiling for ${b:,.0f}")
        tiers.append({"name": f"{o['name']} tier {k}", "type": "amortizing", "group": o["name"],
                      "weeks": o["weeks"], "min": a, "max": b, "annual_rate": rate,
                      "months": o.get("months", 120), "fee_share": fee_share,
                      "prepayable": o.get("prepayable", True), "payoff_discount": 0.0,
                      "prepay_penalty": o.get("prepay_penalty", 0.0), "source": "sba_7a"})
    return tiers


def expand_offers(scenario: dict) -> List[dict]:
    out = []
    for o in scenario.get("offers", []):
        if o["type"] == "sba_7a":
            out += sba_tiers(o)
        else:
            out.append(dict(o))
    return out


def profiles(o: dict, T: int):
    if o["type"] == "mca":
        return mca_profile(o, T)
    if o["type"] == "amortizing":
        return amortizing_profile(o["annual_rate"], o["months"], T)
    raise ValueError(f"offer type {o['type']!r} is not supported by the optimizer")


# ---------------------------------------------------------------- the model

class Model:
    """A sparse MILP: maximize obj . x + constant subject to lo <= A x <= hi, lb <= x <= ub."""

    def __init__(self):
        self.names: List[tuple] = []
        self.index: Dict[tuple, int] = {}
        self.lb: List[float] = []
        self.ub: List[float] = []
        self.integer: List[int] = []
        self.rows: List[Dict[int, float]] = []
        self.row_names: List[tuple] = []
        self.lo: List[float] = []
        self.hi: List[float] = []
        self.obj: Dict[int, float] = {}
        self.constant = 0.0

    def var(self, name, lb=0.0, ub=math.inf, integer=False):
        self.index[name] = len(self.names)
        self.names.append(name)
        self.lb.append(lb)
        self.ub.append(ub)
        self.integer.append(1 if integer else 0)
        return name

    def row(self, name, coefs, lo, hi):
        r: Dict[int, float] = {}
        for k, v in coefs:
            if v:
                i = self.index[k]
                r[i] = r.get(i, 0.0) + v
        self.rows.append(r)
        self.row_names.append(name)
        self.lo.append(lo)
        self.hi.append(hi)

    def to_json(self):
        enc = lambda v: v if math.isfinite(v) else ("inf" if v > 0 else "-inf")
        return {"vars": [list(map(str, n)) for n in self.names], "lb": list(map(enc, self.lb)),
                "ub": list(map(enc, self.ub)), "integer": self.integer,
                "rows": [{"name": list(map(str, n)), "coefs": {str(k): v for k, v in r.items()},
                          "lo": enc(l), "hi": enc(h)} for n, r, l, h in zip(self.row_names, self.rows, self.lo, self.hi)],
                "objective": {str(k): v for k, v in self.obj.items()}, "constant": self.constant}


def _series(v, T, default=0.0):
    if v is None:
        return [default] * (T + 1)
    if isinstance(v, (int, float)):
        return [float(v)] * (T + 1)
    v = list(v)
    if len(v) == T:
        return [None] + [float(a) for a in v]
    if len(v) == T + 1:
        return [float(a) if a is not None else None for a in v]
    raise ValueError(f"series must have T={T} values (weeks 1..T)")


def invoices(scenario: dict) -> List[dict]:
    """Supplier invoices: explicit list, or a recurring rule {"amount", "weeks", "discount",
    "discount_lag", "net_lag"} (lags in weeks after receipt)."""
    out = list(scenario.get("invoices", []))
    rec = scenario.get("recurring_invoices")
    if rec:
        a, b = rec["weeks"]
        for w in range(a, b + 1):
            out.append({"week": w, "amount": rec["amount"], "discount": rec["discount"],
                        "discount_week": w + rec["discount_lag"], "net_week": w + rec["net_lag"]})
    return out


def build_model(scenario: dict, H: float = 0.0, force: Dict[str, float] | None = None,
                relax: bool = False) -> Tuple[Model, dict]:
    """Build the MILP. ``force`` = {offer name: amount} fixes an offer's amount (for baselines)."""
    sc = scenario
    T = int(sc["horizon_weeks"])
    B0 = float(sc["starting_cash"])
    floor = _series(sc.get("cash_floor", 0.0), T)
    R = _series(sc.get("revenue", 0.0), T)
    c = _series(sc["operating_cash_flow"], T)
    alpha = sc.get("affordability_share", 1.0)
    idep = sc.get("deposit_rate", 0.0) / 52
    loc = sc.get("line_of_credit")
    iL = loc["annual_rate"] / 52 if loc else 0.0
    UL = loc["limit"] if loc else 0.0
    loc_b0 = loc.get("balance", 0.0) if loc else 0.0
    loc_fee = loc.get("draw_fee", 0.0) if loc else 0.0
    inv = invoices(sc)
    fac = sc.get("factoring")
    offers = expand_offers(sc)
    force = force or {}

    m = Model()
    info = {"T": T, "offers": {}, "invoices": inv, "factoring": fac, "H": H, "force": force}

    # --- offers
    X: Dict[str, List[tuple]] = {}
    for o in offers:
        kk, rho, r_week = profiles(o, T)
        a, b = o.get("weeks", [1, T])
        S = [s for s in range(max(1, a), min(T, b) + 1)]
        U = (lambda s: list(range(s + 1, T + 1)) + [NEVER]) if o.get("prepayable", True) else (lambda s: [NEVER])
        L, Umax = float(o.get("min", 0.0)), float(o["max"])
        group_name = o.get("group", o["name"])
        if group_name in force or o["name"] in force:
            amt = force.get(o["name"], force.get(group_name))
            if amt is not None and not (L - 1e-9 <= amt <= Umax + 1e-9):
                S = []           # this tier cannot carry the forced amount
            elif amt is not None:
                L = Umax = float(amt)
        fee = o.get("fee_share", o.get("fee", 0.0))
        pi = o.get("payoff_discount", 0.0)
        pen = o.get("prepay_penalty", 0.0)
        info["offers"][o["name"]] = {"spec": o, "k": kk, "rho": rho, "r_week": r_week, "fee": fee,
                                     "pi": pi, "penalty": pen, "group": group_name}
        X[o["name"]] = []
        for s in S:
            for u in U(s):
                m.var(("x", o["name"], s, u), 0.0, Umax)
                m.var(("z", o["name"], s, u), 0.0, 1.0, integer=not relax)
                X[o["name"]].append((s, u))
                m.row(("min", o["name"], s, u), [(("x", o["name"], s, u), 1.0), (("z", o["name"], s, u), -L)], 0.0, math.inf)
                m.row(("max", o["name"], s, u), [(("x", o["name"], s, u), 1.0), (("z", o["name"], s, u), -Umax)], -math.inf, 0.0)
        m.row(("once", o["name"]), [(("z", o["name"], s, u), 1.0) for s, u in X[o["name"]]], -math.inf, 1.0)
    groups: Dict[str, List[str]] = {}
    for o in offers:
        groups.setdefault(o.get("group", o["name"]), []).append(o["name"])
    for g, members in groups.items():
        if len(members) > 1:
            m.row(("group", g), [(("z", j, s, u), 1.0) for j in members for s, u in X[j]], -math.inf, 1.0)
    for g, amt in force.items():          # a forced offer must be taken
        members = groups.get(g, [g])
        m.row(("force", g), [(("z", j, s, u), 1.0) for j in members for s, u in X.get(j, [])], 1.0, 1.0)

    # --- LOC, cash, invoices, factoring
    for t in range(1, T + 1):
        if loc:
            m.var(("d", t))
            m.var(("p", t))
            m.var(("b", t), 0.0, UL)
        m.var(("B", t), floor[t] if floor[t] is not None else 0.0)
    E = []
    for n, i in enumerate(inv):
        if i["discount_week"] <= T and i.get("discount", 0) > 0:
            m.var(("e", n), 0.0, 1.0)
            E.append(n)
    recv = fac.get("receivables", []) if fac else []
    Y = []
    if fac:
        for n, r in enumerate(recv):
            if not r.get("eligible", True):
                continue
            for q in range(max(1, r["issue_week"]), min(r["collect_week"] - 1, T) + 1):
                m.var(("y", n, q), 0.0, 1.0)
                Y.append((n, q))

    def fac_fee(n, q):
        r = recv[n]
        days = (r["collect_week"] - q) * 7
        return fac["fee_per_30_days"] * math.ceil(days / 30 - 1e-12)

    aF = fac["advance_rate"] if fac else 0.0

    for t in range(1, T + 1):
        cs = [(("B", t), 1.0)]
        k0 = c[t]
        if t > 1:
            cs.append((("B", t - 1), -(1 + idep)))
        else:
            k0 += (1 + idep) * B0
        aff = []
        for name, (o) in ((n_, info["offers"][n_]) for n_ in X):
            for s, u in X[name]:
                coef = 0.0
                if s == t:
                    coef -= (1 - o["fee"])
                if s < t and (u == NEVER or t <= u):
                    kt = o["k"].get(t - s, 0.0)
                    coef += kt
                    if kt:
                        aff.append((("x", name, s, u), kt))
                if u == t:
                    coef += (1 - o["pi"]) * (1 + o["penalty"]) * o["rho"][u - s]
                if coef:
                    cs.append((("x", name, s, u), coef))
        if loc:
            cs += [(("d", t), -(1 - loc_fee)), (("p", t), 1.0)]
            if t > 1:
                cs.append((("b", t - 1), iL))
                aff.append((("b", t - 1), iL))
            else:
                k0 -= iL * loc_b0
        for n, i in enumerate(inv):
            if i["discount_week"] == t and n in E:
                cs.append((("e", n), (1 - i["discount"]) * i["amount"]))
            if i["net_week"] == t:
                k0 -= i["amount"]
                if n in E:
                    cs.append((("e", n), -i["amount"]))
        for n, q in Y:
            if q == t:
                cs.append((("y", n, q), -aF * recv[n]["face"]))
        for n, r in enumerate(recv):
            if r["collect_week"] == t:
                k0 += r["face"]
                for n2, q in Y:
                    if n2 == n:
                        cs.append((("y", n, q), (aF + fac_fee(n, q)) * r["face"]))   # face goes to the factor; rebate = face - aF - fee
        m.row(("cash", t), cs, k0, k0)
        if loc:
            lc = [(("b", t), 1.0), (("d", t), -1.0), (("p", t), 1.0)]
            m.row(("loc", t), lc + ([(("b", t - 1), -1.0)] if t > 1 else []), loc_b0 if t == 1 else 0.0,
                  loc_b0 if t == 1 else 0.0)
        cap = alpha * R[t] if R[t] is not None else math.inf
        if alpha < 1.0 or sc.get("revenue") is not None:
            k_aff = iL * loc_b0 if (loc and t == 1) else 0.0
            m.row(("afford", t), aff, -math.inf, cap - k_aff)
        if fac:
            out_adv = [(("y", n, q), aF * recv[n]["face"]) for n, q in Y if q <= t < recv[n]["collect_week"]]
            if out_adv:
                m.row(("fac_limit", t), out_adv, -math.inf, fac["limit"])
    for n, r in enumerate(recv):
        ys = [(("y", n2, q), 1.0) for n2, q in Y if n2 == n]
        if ys:
            m.row(("sell_once", n), ys, -math.inf, 1.0)

    dscr = sc.get("dscr")
    if dscr:
        ds = []
        for name in X:
            o = info["offers"][name]
            for s, u in X[name]:
                tot = sum(o["k"].get(t - s, 0.0) for t in range(s + 1, T + 1) if u == NEVER or t <= u)
                if tot:
                    ds.append((("x", name, s, u), tot))
        if loc:
            ds += [(("b", t), iL) for t in range(1, T)]
        m.row(("dscr",), ds, -math.inf, dscr["ebitda"] / dscr["min"] - (iL * loc_b0 if loc else 0.0))

    # --- objective: terminal net position with post-horizon carry H
    m.obj[m.index[("B", T)]] = 1 + idep * H
    if loc:
        m.obj[m.index[("b", T)]] = -(1 + iL * H)
    for name in X:
        o = info["offers"][name]
        for s, u in X[name]:
            if u == NEVER:
                m.obj[m.index[("x", name, s, u)]] = -o["rho"][T - s] * (1 + o["r_week"] * H)
    for n, i in enumerate(inv):
        if i["net_week"] > T:
            m.constant -= i["amount"]
            if n in E:
                m.obj[m.index[("e", n)]] = m.obj.get(m.index[("e", n)], 0.0) + i["amount"]
    for n, r in enumerate(recv):
        if r["collect_week"] > T:
            m.constant += r["face"]
            for n2, q in Y:
                if n2 == n:
                    j = m.index[("y", n, q)]
                    # still to collect: unfactored part F(1-y) + rebate (1 - aF - fee) F y; the advance
                    # aF F y is already in cash B_T, so the claim falls by (aF + fee) F y.
                    m.obj[j] = m.obj.get(j, 0.0) - (aF + fac_fee(n, q)) * r["face"]
    # Early payment of invoices received inside the horizon whose net date is beyond T but whose
    # discount week is inside: already handled (paid early in-window, removed from terminal liability).
    info["fac_fee"] = {(n, q): fac_fee(n, q) for n, q in Y}
    info["X"] = X
    info["E"] = E
    info["Y"] = Y
    info["advance_rate"] = aF
    return m, info
