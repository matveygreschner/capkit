# California and New York disclosure rules behind each figure

Text checked on law.cornell.edu on 2026-11-26. CapKit reproduces the math. Compliance remains the
provider's responsibility.

## Coverage
- **California:** offers of **$500,000 or less** (Fin. Code §22800(n)). Exempt: depository
  institutions, real-estate-secured transactions, providers making one transaction (or five
  incidental ones) in 12 months, and certain vehicle dealer and rental deals (§22801). §921 says how
  offer size is measured.
- **New York:** offers of **$2,500,000 or less** (23 NYCRR 600.19). The amount is the credit limit for
  open-end financing and the amount financed otherwise. Asset-based lending and factoring have their
  own tests.

## APR method
- **CA 10 CCR 940(a):** "either the United States Rule method or the actuarial method, as both are set
  forth in Appendix J, 12 C.F.R. Part 1026". The APR includes all finance charges under §943.
- **NY 23 NYCRR 600.3(b):** the same two methods.
- **CapKit:** the checker computes both methods and accepts a disclosure that matches either.

## Historical method (estimated sales)
- **CA 10 CCR 930 / NY 600.8.** The projection is the recipient's **average monthly sales** over a
  provider-fixed window of **4 to 12 months**. It includes sales from other channels the contract would
  redirect. A business with a shorter history may use the months it has operated.
- The provider may exclude below-average months caused by a non-recurring event, undocumented months,
  and the oldest months if documentation was not required for them.
- **NY alternative:** "average sales for the same number of months with the highest sales volume
  within the past twelve months" (`window_method: "highest"`).
- **Opt-in method** (CA §931, NY §600.9): an internal projection with periodic audits. CapKit does not
  model the audits.

## Estimated payments, term and APR
- **CA 10 CCR 942 / NY 600.7.** These are computed from the projection, taking into account:
  - specified payment amounts;
  - split-rate changes;
  - contractual minimum payments;
  - payments required when sales fall below a threshold;
  - reasonably anticipated true-ups and other finance charges.
- **CapKit's stated assumption** (the regulations give no closed form):
  - estimated payment per business day = split rate × average monthly sales × 12 ÷ the business days
    in the 12 months after funding, on the Federal Reserve calendar, with any contractual minimum
    applied;
  - debits run until the total owed is collected;
  - the estimated term is the time to the last debit;
  - the estimated APR is Appendix J applied to that schedule, with a one-day unit period.
- **Estimated monthly cost** (CA §900(a)(12)) = total payments ÷ (term days ÷ 30.4).

## Disclosure table
- **CA §914:** Funding Provided; Estimated APR (with the assumed monthly income); Finance Charge;
  Estimated Total Payment Amount; Estimated Payment; Payment Terms; Estimated Term; Prepayment (two
  rows).
- If payments are not monthly, an **Estimated Monthly Cost** row is added after Estimated Total
  Payment Amount.
- **NY §600.6:** the same rows, plus **Collateral Requirements**.

## Tolerance
- **NY 600.4:** 1/8 percentage point; 1/4 for irregular transactions; or a percentage difference
  (determined − disclosed) / disclosed × 100 of **2.5% or less**.
- **CA:** no separate tolerance provision was located in the subchapter. CapKit compares at the Reg Z
  1/8 point for reference and labels it that way.

## Verify before relying on it
- The Cal. Fin. Code §22802 text.
- The full text of 10 CCR §921.
- Amendments after 2024.
- Whether the bill on DFPI approval of the underwriting method was enacted.
