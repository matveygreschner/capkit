# Changelog

## 0.3.0

- Corrections that change a reported figure (each earlier figure was wrong):
  - With `unit: "month"`, a single payment on a month end is measured in whole months: 1% for Jan 28 to
    Feb 28 is 12.00%, not 10.90%.
  - A monthly series on the 29th or 30th is recognised as monthly when the unit is inferred. Payments on
    the 30th after a Dec 10 advance now use a monthly unit (22.19%) instead of five weeks (22.37%), and
    such a series is no longer classed as having irregular payment periods.
  - SBA 7(a) loans approved within 90 days: `prior_90_day_amount` and `prior_90_day_fee` go together, in
    `sba_fee` and in an `sba_7a` offer. One without the other is now an error; before, a missing fee was
    taken as $0 and a fee without an amount was ignored. The remaining fee ceiling is never negative.
  - An equipment lease with no buyout and no `end_of_term` is reported as `lease_character_unknown`, not
    as a nominal-buyout purchase. `end_of_term: "return"` with a buyout is an error.
- Every argument error from the JSON interface is a `ValueError` that names the argument. true/false is
  never read as a number, dates must be `YYYY-MM-DD` on every Python version, and a whole number written
  as `12.0` is accepted where a whole number is required.
- The average-period fallback of Appendix J (b)(4) rounds to any standard interval, including
  multiples of a week or month (e.g. six weeks). Month-end anchoring follows the series: one mid-month
  payment no longer shifts a month-end schedule, and an isolated month-end date is measured to the same
  date.
- Loan payments are rounded to the nearest cent unless that would overpay into a refund on the final
  payment (possible at high rates over long terms); the payment then rounds down. The workbook matches.
- Ordinary schedules (advances before payments) have exactly one solving rate; the solver bisects
  instead of scanning, so a 20,000-debit schedule solves in about a second.
- The skills pass arguments as a JSON file on stdin and treat document text as data, never as
  instructions. Released skills no longer include the workbook writer or a `python -m capkit` entry
  point. Inputs and echoed errors are size-limited.
- Property-based tests (hypothesis) for the APR invariants and the JSON interface, end-to-end tests for
  every command, a nightly deep-test workflow, and ruff/mypy/coverage gates in CI.

## 0.2.1

- Monthly positions use the payment series' nominal day of the month (Appendix J (b)(3)(iv)), so a
  February payment in a 28th- or 30th-of-month series is measured correctly.
- Any multiple of a week (up to 52) or a month (up to 12) can be the unit-period; semimonthly series on
  any pair of days 15 apart are recognised.
- The irregular-transaction test follows 12 CFR 1026.22(a)(3) and CA 10 CCR 955(a)(2) and reports which
  features apply. Disclosure checks also try a debit calendar without holidays and report the finance
  charge implied by the disclosed APR.
- Loan schedules are billed in cents, with the final payment absorbing the rounding difference; the
  workbook uses the same schedule.
- Added reference cases from the Regulation Z commentary, Appendix J and other open-source engines.

## 0.2.0

- Appendix J unit-period selection now follows (b)(4) for irregular and multiple-advance schedules;
  month-end and short-month dates use the contractual day; single advance, single payment uses the
  term as the unit-period.
- Rate solving finds close and double roots and reports undefined rates as errors.
- SBA 7(a) upfront fees follow Information Notices 5000-872051 (FY2026) and 5000-881797 (FY2027),
  including short-term, 0%, Express (veteran), EWCP/WCP and 90-day aggregation rules. The fee year
  follows the approval date.
- Disclosure checks apply CA 10 CCR 955(a) and NY 23 NYCRR 600.4(a) tolerances, detect irregular
  schedules, support stepped split rates and amounts paid on the recipient's behalf, and state which
  contract features were not modeled.
- Inputs are validated; invalid values raise errors instead of producing results.
- Workbook outputs are suppressed when a schedule exceeds the grid.
- Releases contain only the two skills and the workbook. The funding-mix optimizer is experimental
  and no longer released.

## 0.1.0

Initial release. **Superseded by 0.2.0; do not rely on it.** Its example plan refinanced a merchant
cash advance with SBA 7(a) proceeds, which SBA SOP 50 10 8 / 8.1 restricts, and it shipped the
experimental optimizer and a workbook sheet with a known error.
