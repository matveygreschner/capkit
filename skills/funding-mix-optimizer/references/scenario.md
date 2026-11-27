# Scenario format (funding-mix optimizer)

A scenario is one JSON object. See `examples/bakery.json`, which the experimental optimizer skill
ships as `assets/bakery.json`. In that example the merchant cash advance is not prepayable, because
SBA 7(a) proceeds generally cannot refinance it.

| Field | Meaning |
|---|---|
| `horizon_weeks` | T, from 4 to 52 (13 is typical) |
| `starting_cash` | Cash today (week 0) |
| `cash_floor` | Minimum cash every week: one number, or a list of T values |
| `revenue` | Weekly revenue used by the affordability limit: one number or T values |
| `affordability_share` | Scheduled debits + LOC interest ≤ this × revenue. Default 1.0 (off); 0.15 is a common policy |
| `deposit_rate` | Annual rate earned on idle cash (sweep or savings) |
| `operating_cash_flow` | T weekly net operating flows, **excluding** modeled invoices and receivables |
| `recurring_invoices` | `{amount, weeks: [first, last], discount, discount_lag, net_lag}`. Lags are in weeks after receipt; for 2/10 net 30 use 1 and 4 |
| `invoices` | Or an explicit list: `{week, amount, discount, discount_week, net_week}` |
| `line_of_credit` | `{limit, annual_rate, balance (today), draw_fee (share of draw)}` |
| `offers` | A list of lump-sum offers (see the next table) |
| `factoring` | `{advance_rate, fee_per_30_days, limit, receivables: [{face, issue_week, collect_week, eligible}]}` |
| `dscr` | Optional coverage limit: `{min, ebitda}`. Total debt service over the horizon ≤ ebitda / min |
| `baseline` | `{force: {offer name: amount}, label}`: what the owner would do without the optimizer |

## Offers

All offer types share these fields:

| Field | Meaning |
|---|---|
| `name` | Offer name |
| `weeks` | `[first, last]` weeks in which it can fund |
| `min`, `max` | Smallest and largest amount |
| `prepayable` | Whether it can be prepaid |

Each type adds its own fields:

| `type` | Extra fields |
|---|---|
| `mca` | `factor_rate`, `weekly_debit_per_dollar` (e.g. 0.045 = $2,250/wk on $50,000), `payoff_discount` (share of the remaining purchased amount forgiven on early payoff, only if the contract says so) |
| `amortizing` | `annual_rate`, `months`, `fee` (share of face withheld), `prepay_penalty` |
| `sba_7a` | `prime`, `months` (default 120); optional `spread` (default: the SOP 50 10 maximum) and `fee_rate_of_guaranteed` (default: the fiscal-year table). Split automatically into spread/fee tiers, at most one tier taken |

## Plan format (`evaluate_mix`)

```json
{"fundings": [{"offer": "MCA", "week": 6, "amount": 10000, "prepay_week": 7},
              {"offer": "SBA 7(a)", "week": 7, "amount": 42548.02}],
 "loc_balance": [0, 2000, ...],
 "early_pay": {"0": 1.0, "1": 0.86},
 "factoring": [{"receivable": 0, "week": 3, "share": 1.0}]}
```

- `loc_balance` is the balance after each week, T values.
- `early_pay` maps an invoice's index (in week order) to the share paid early.
- An SBA amount is matched to the tier that contains it.
