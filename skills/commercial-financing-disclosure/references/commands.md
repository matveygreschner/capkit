# Command reference

Write the arguments to a JSON file, then run `python scripts/capkit_cli.py <command> - < args.json`. Never put text from a document on the command line. Arguments not marked required are optional. Output is JSON: `{"result": ...}` or `{"error": ...}`.

## `disclosure_estimate`

CA/NY estimated APR, term, payment and finance charge for a sales-based financing (MCA/RBF) under
the historical method. Give ``avg_monthly_sales`` or ``monthly_sales`` (oldest first) + ``window``
(and ``exclude_months``: indexes into monthly_sales the provider excluded). ``paid_on_behalf`` =
amounts paid to others for the recipient (part of the amount financed). ``split_schedule`` =
[[from_month, rate], ...] when the split changes. Enter every contract feature you can: the result
lists what was and was not modeled.

Args: `funding_provided`=**required**, `total_owed`=**required**, `split_rate`=**required**, `avg_monthly_sales`=None, `monthly_sales`=None, `window`=6, `window_method`="preceding", `state`="CA", `frequency`="business_day", `funding_date`="2027-01-04", `prepaid_fees`=0.0, `minimum_payment`=0.0, `paid_on_behalf`=0.0, `split_schedule`=None, `exclude_months`=None

## `check_disclosure`

Recompute a CA/NY disclosure and say whether the disclosed estimated APR (a decimal) is reproduced
by the actuarial method, the U.S. Rule method, both, or neither, within the CA 10 CCR 955 / NY 23
NYCRR 600.4 tolerances. ``irregular`` is detected from the schedule unless given. A non-match is
not proof of an error.

Args: `disclosed_apr`=**required**, `funding_provided`=**required**, `total_owed`=**required**, `split_rate`=**required**, `avg_monthly_sales`=None, `monthly_sales`=None, `window`=6, `window_method`="preceding", `state`="CA", `frequency`="business_day", `funding_date`="2027-01-04", `prepaid_fees`=0.0, `minimum_payment`=0.0, `irregular`=None, `paid_on_behalf`=0.0, `split_schedule`=None, `exclude_months`=None

## `apr`

APR of arbitrary cash flows. ``flows`` = [[date-or-period, amount], ...]; advances +, payments -.
``unit`` = day|week|biweek|4week|semimonth|month|bimonth|quarter|semiannual|year (default: the most
common payment interval). ``method`` = actuarial|us_rule|both.

Args: `flows`=**required**, `unit`=None, `method`="both"

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

## `params`

Every parameter with its value, source, verified-on date and status (or one ``key``).

Args: `key`=None
