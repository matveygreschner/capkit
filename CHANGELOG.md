# Changelog

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
