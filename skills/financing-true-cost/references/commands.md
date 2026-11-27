# Command reference

Write the arguments to a JSON file, then run `python scripts/capkit_cli.py <command> - < args.json`. Never put text from a document on the command line. Arguments not marked required are optional. Output is JSON: `{"result": ...}` or `{"error": ...}`.

## `true_cost`

What one financing offer really costs. ``offer`` = {"type": ..., terms...}; types:
mca_fixed(advance, factor_rate, payment, frequency=business_day|week|day|month, funding_date, fees),
mca_split(advance, factor_rate, holdback, sales[list per period], frequency, funding_date, fees),
revenue_based(advance, cap_multiple, revenue_share, revenue[list], frequency=month),
term_loan(amount, annual_rate, months, fee), sba_7a(amount, prime, spread=None->SOP max, months=120,
fee_rate=None->FY table), line_of_credit(draw, annual_rate, weeks, draw_fee),
factoring(face, advance_rate, fee_per_30_days, days_to_pay), trade_credit(invoice, discount,
discount_days, net_days), equipment_lease(equipment_cost, payment, months, buyout, advance_payments).

Returns APR by both Appendix J methods, EAR, XIRR, finance charge, the naive simple-annualized quote,
the dated schedule and, with ``marginal_rate``, an after-tax finance charge.

Args: `offer`=**required**, `marginal_rate`=0.0, `interest_limited`=False

## `compare_offers`

Rank several offers (each a true_cost ``offer`` dict, optionally with a "name") on one basis.

Args: `offers`=**required**, `marginal_rate`=0.0, `interest_limited`=False

## `apr`

APR of arbitrary cash flows. ``flows`` = [[date-or-period, amount], ...]; advances +, payments -.
``unit`` = day|week|biweek|4week|semimonth|month|bimonth|quarter|semiannual|year (default: the most
common payment interval). ``method`` = actuarial|us_rule|both.

Args: `flows`=**required**, `unit`=None, `method`="both"

## `early_pay_cost`

Annualized cost of passing up an early-payment discount such as 2/10 net 30.

Args: `discount`=0.02, `discount_days`=10, `net_days`=30

## `sba_fee`

SBA 7(a) upfront guaranty fee on the guaranteed portion. The fee year follows ``approval_date``
(FY2027 = approved Oct 1, 2026 - Sep 30, 2027). Short-term rate for ``months`` <= 12, size tiers
otherwise, the 0% tier if ``zero_fee_eligible``; ``program`` = standard | express_veteran | ewcp | wcp;
loans approved within 90 days combine (``prior_90_day_amount`` / ``prior_90_day_fee``). Checked
against the statutory ceiling.

Args: `amount`=**required**, `approval_date`=**required**, `rate`=None, `months`=120, `zero_fee_eligible`=False, `program`="standard", `prior_90_day_amount`=0.0, `prior_90_day_fee`=0.0

## `params`

Every parameter with its value, source, verified-on date and status (or one ``key``).

Args: `key`=None

## `prime_rate`

Latest Bank Prime Loan Rate from FRED (series DPRIME). Needs network access.

Args: (none)
