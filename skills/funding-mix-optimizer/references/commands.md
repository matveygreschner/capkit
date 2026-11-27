# Command reference

Write the arguments to a JSON file, then run `python scripts/capkit_cli.py <command> - < args.json`. Never put text from a document on the command line. Arguments not marked required are optional. Output is JSON: `{"result": ...}` or `{"error": ...}`.

## `optimize_mix`

Cheapest funding mix for a weekly cash forecast (needs scipy >= 1.9). See examples/bakery.json for
the scenario format. Reports the plan at post-horizon carries H=0 and H=52, the saving versus the
scenario's baseline, floor sensitivity, and an independent re-pricing check of every plan.

Args: `scenario`=**required**, `carries`=[0, 52], `sensitivity`=True, `time_limit`=60.0

## `evaluate_mix`

Check any proposed plan (stdlib, no solver): feasibility, every violated rule, weekly cash and
terminal net position. ``plan`` = {"fundings": [{"offer", "week", "amount", "prepay_week"}],
"loc_balance": [balance after each week], "early_pay": {invoice_index: share},
"factoring": [{"receivable", "week", "share"}]}.

Args: `scenario`=**required**, `plan`=**required**, `H`=0.0

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

## `early_pay_cost`

Annualized cost of passing up an early-payment discount such as 2/10 net 30.

Args: `discount`=0.02, `discount_days`=10, `net_days`=30

## `workbook`

Generate the formula-driven Excel / Google Sheets workbook.

Args: `path`="CapKit.xlsx"

## `params`

Every parameter with its value, source, verified-on date and status (or one ``key``).

Args: `key`=None
