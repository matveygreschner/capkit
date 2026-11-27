"""Side-by-side comparison of financing offers on one cash-flow basis, with an after-tax view.

After-tax cost uses each product's tax-character tag rather than assuming everything is interest:

* ``interest`` (term loans, SBA, LOC): deductible as business interest, subject to the section 163(j)
  limit unless the business meets the small-business gross-receipts exemption (section 448(c));
  ``interest_limited=True`` turns the deduction off for a business over the limit.
* ``character_uncertain`` (MCA factor cost, factoring discount): if respected as a sale of receivables
  the discount is plausibly an ordinary deduction/loss rather than interest; if recharacterized as debt
  it is interest. Default: deductible, flagged, with the "treated as interest and limited" alternative.
* ``rent`` (true leases): deductible rent. ``purchase_cost`` (forgone discounts): part of inventory cost.

The marginal rate is an input (federal + state). TaxKit (sibling project) can supply it: compute the
owner's return with and without the deduction. These treatments need a tax professional's review.
"""
from __future__ import annotations

from typing import List

from .products import analyze, build


def after_tax_cost(finance_charge: float, character: str, marginal_rate: float,
                   interest_limited: bool = False) -> dict:
    deductible = {"interest": not interest_limited, "character_uncertain": True, "rent": True,
                  "purchase_cost": True}.get(character, False)
    cost = finance_charge * (1 - marginal_rate * deductible)
    out = {"after_tax_finance_charge": round(cost, 2), "assumed_deductible": deductible}
    if character == "character_uncertain":
        alt = finance_charge * (1 - marginal_rate * (not interest_limited))
        out["if_treated_as_interest"] = round(alt, 2)
        out["flag"] = "Tax character uncertain (sale of receivables vs. debt); confirm with a tax professional."
    return out


def compare(offers: List[dict], marginal_rate: float = 0.0, interest_limited: bool = False) -> dict:
    """Analyze every offer spec (see products.build) and rank by actuarial APR."""
    rows = []
    for spec in offers:
        s = build(spec)
        a = analyze(s)
        a["name"] = spec.get("name", spec["type"])
        if marginal_rate:
            a.update(after_tax_cost(a["finance_charge"], a["tax_character"], marginal_rate, interest_limited))
        rows.append(a)
    rows.sort(key=lambda r: r["apr_actuarial"])
    for k, r in enumerate(rows, 1):
        r["rank"] = k
    return {"offers": rows,
            "note": "APR ranks the price of money; total dollar cost and peak payment matter too. "
                    "A cheaper APR that funds later or needs collateral may not solve the cash need."}
