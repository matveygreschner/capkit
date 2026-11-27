---
name: commercial-financing-disclosure
description: Reproduces and checks California (SB 1235, 10 CCR 900 et seq.) and New York (Commercial Finance Disclosure Law, 23 NYCRR Part 600) commercial financing disclosures for sales-based financing such as merchant cash advances and revenue-based financing. It computes the historical-method average sales, estimated payment, estimated term, finance charge, estimated monthly cost and the estimated APR by both permitted Regulation Z Appendix J methods, then says whether a disclosed APR is consistent with the actuarial method, the U.S. Rule method, or neither, citing the section for each line. Use this whenever someone has an MCA or RBF disclosure form and asks if the numbers are right, wants to know how the estimated APR or term was calculated, needs to build a CA or NY disclosure for an offer, or is studying SB 1235 / CFDL math, even if they only paste the disclosure table.
---

# Commercial financing disclosure (CA / NY)

Recomputes the "estimated" figures on a California or New York sales-based financing disclosure
and checks the disclosed APR. The bundled **CapKit** engine implements the historical method and
both Appendix J APR methods. It is an **educational and self-checking tool, not a compliance
certification.** Say so in every answer.

## Workflow

### 1. Collect the inputs
From the disclosure or the contract:
- funding provided, total amount owed (purchased amount), prepaid fees, split rate (holdback %),
  payment frequency (usually business-day debits), funding date, any contractual minimum payment;
- the sales history: monthly sales, oldest first, and the provider's averaging window (4–12 months).
  New York also allows the average of the highest-sales months within the past twelve
  (`window_method: "highest"`).
- the state (CA or NY) and the disclosed estimated APR, if checking.

If the user only has the provider's stated "assumed average monthly sales", pass it as
`avg_monthly_sales`.

### 2. Run it
```bash
python scripts/capkit_cli.py disclosure_estimate '{"funding_provided": 50000, "total_owed": 67500, "split_rate": 0.10, "monthly_sales": [61000, 59000, 60000, 62000, 58000, 60000], "window": 6, "state": "CA"}'
python scripts/capkit_cli.py check_disclosure '{"disclosed_apr": 0.6775, "funding_provided": 50000, "total_owed": 67500, "split_rate": 0.10, "avg_monthly_sales": 60000, "state": "NY"}'
```

### 3. Report
Lay the result out like the disclosure table (CA §914 / NY §600.6 rows): Funding Provided, Estimated
APR, Finance Charge, Estimated Total Payment Amount, Estimated Payment, Estimated Term, and Estimated
Monthly Cost when payments aren't monthly. Then:
- **Verdict:** "consistent (actuarial method)", "consistent (U.S. Rule method)", or "not reproduced by
  either permitted method with these inputs". Never flag a disclosure that matches *either* method, and
  never call a non-match an error or a violation: list the unmodeled contract features the tool returns
  (true-ups, stepped splits, thresholds, different sales data) and say what would need checking. Both are allowed
  (10 CCR 940(a); 23 NYCRR 600.3(b)).
- **Tolerance:** CA (10 CCR 955(a)) and NY (23 NYCRR 600.4(a)) treat a disclosed APR as accurate
  within 1/8 point (1/4 if the schedule is irregular, which the tool detects) **or** when the signed
  percentage difference (determined − disclosed) / disclosed is 2.5% or less.
- **Enter every contract feature you can:** a split that changes over time (`split_schedule`),
  amounts paid to others on the merchant's behalf (`paid_on_behalf`, which count toward the
  coverage threshold), excluded months (`exclude_months`). Always report the `modeled` /
  `not_modeled` lists, even when the verdict is "consistent".
- **Where a mismatch comes from:** a different sales average or window, a different payment-days
  calendar, fees left out of the finance charge, or minimum payments. Re-run with alternatives to
  show which assumption reproduces the disclosed figure.

Read `references/rules.md` for the regulation text behind each line and the assumption CapKit
states: monthly sales spread evenly over the business days in the 12 months after funding, on the
Federal Reserve holiday calendar.

## Guardrails
- Coverage: CA offers of $500,000 or less; NY offers of $2,500,000 or less, with exemptions (banks,
  real-estate-secured, very small providers). Check the `covered` field.
- An MCA is usually structured as a purchase of receivables; whether a particular contract is a loan is
  a legal question. Never call it a loan. The estimated APR is a disclosure metric.
- For an actual compliance program, the provider's counsel must review. This tool reproduces the math.
