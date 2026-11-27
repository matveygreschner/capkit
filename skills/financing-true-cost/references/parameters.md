# Parameters

Generated from `capkit/params.py`. `verify` = best available figure, re-check against the source before relying on it; `placeholder` = example value only.

| Key | Value | Description | Source | Verified on | Status |
|---|---|---|---|---|---|
| `regz_tolerance_regular` | 12.5000% | APR accuracy tolerance for a regular transaction | 12 CFR 1026.22(a)(2) | 2026-11-26 | verified |
| `regz_tolerance_irregular` | 25.0000% | APR accuracy tolerance for an irregular transaction (multiple advances, irregular payment periods or amounts, other than an irregular first period or first/final payment) | 12 CFR 1026.22(a)(3) | 2026-11-26 | verified |
| `appj_days_per_month` | 30 | Days in a month when counting a fractional unit period (a month is 30 days; the alternative of 1/365 of a year is not used) | 12 CFR 1026 Appendix J (b)(5)(iv) | 2026-11-26 | verified |
| `ca_cfdl_max_amount` | 500,000 | California commercial financing disclosures apply to offers of $500,000 or less | Cal. Fin. Code 22800-22805; 10 CCR 900 et seq. | 2026-11-26 | verify |
| `ny_cfdl_max_amount` | 2,500,000 | New York Commercial Finance Disclosure Law applies to offers of $2,500,000 or less | N.Y. Fin. Serv. Law 801-812; 23 NYCRR Part 600 | 2026-11-26 | verify |
| `ca_apr_methods` | ["actuarial", "us_rule"] | California allows the APR to be computed by either Appendix J method | 10 CCR 940(a) | 2026-11-26 | verified |
| `sba_guaranty_share_small` | 85.0000% | SBA guaranty share for 7(a) loans of $150,000 or less | 15 U.S.C. 636(a)(2) | 2026-11-26 | verify |
| `sba_guaranty_share_large` | 75.0000% | SBA guaranty share for 7(a) loans above $150,000 | 15 U.S.C. 636(a)(2) | 2026-11-26 | verify |
| `sba_fee_ceiling` | [[150000, 0.02], [700000, 0.03], [inf, 0.035]] | Statutory ceiling on the upfront guaranty fee by loan amount (up to the bound), as a share of the guaranteed portion; plus 0.25% on guaranteed portion above $1,000,000 | 15 U.S.C. 636(a)(18)(A) | 2026-11-26 | verify |
| `sba_fee_ceiling_extra_over_1m` | 0.2500% | Additional upfront fee ceiling on the part of the guaranteed portion above $1,000,000 | 15 U.S.C. 636(a)(18)(A)(iv) | 2026-11-26 | verify |
| `sba_fee_fy` | {"2026": [[150000, 0.02], [700000, 0.03], [5000000, 0.035]]} | Fiscal-year upfront guaranty fee rates actually charged (can be below the ceiling, including 0% in some years). Placeholder = statutory levels; confirm against the FY notice | SBA 7(a) fiscal-year fee notice (Federal Register / SBA Information Notice) | 2026-11-26 | verify |
| `sba_max_spread` | [[50000, 0.065], [250000, 0.06], [350000, 0.045], [inf, 0.03]] | Maximum variable-rate spread over Prime by loan amount (up to the bound) | SBA SOP 50 10 8 (effective June 1, 2025), maximum allowable interest rates | 2026-11-26 | verify |
| `prime_rate` | 7.0000% | WSJ Prime Rate placeholder used in examples (fetch current: live.prime_rate()) | FRED series DPRIME (Bank Prime Loan Rate) | 2026-11-26 | placeholder |
