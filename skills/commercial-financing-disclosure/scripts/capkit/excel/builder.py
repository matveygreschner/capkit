"""Generate CapKit.xlsx: a formula-driven Excel / Google Sheets workbook generated from the engine.

Portable formulas only (IRR, RATE, PMT, CEILING, WEEKDAY, COUNTIF, SUMPRODUCT, INDEX/MATCH, MIN/MAX,
IF, AND/OR, EDATE). No XLOOKUP, LET, LAMBDA, dynamic arrays, tables, defined names or macros: the test
suite fails the build if any appear. ``scripts/verify_workbook.py`` recalculates the file with an
independent formula engine and compares it with the Python engine.

"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from .. import params as P
from ..calendar import frb_holidays

INPUT = PatternFill("solid", fgColor="FFF2CC")
OUT = PatternFill("solid", fgColor="E2EFDA")
HEAD = Font(bold=True)
TITLE = Font(bold=True, size=14)
PCT = "0.00%"
USD = "$#,##0.00"

DAILY_ROWS = 1100          # calendar days in the daily grids (covers ~3 years)
PERIOD_ROWS = 400          # unit periods in the fixed-period grid
LOAN_ROWS = 360            # months in the loan payment grids


class Cells:
    """Records the address of every named cell for cells.json (used by the verifier)."""

    def __init__(self):
        self.map = {}

    def put(self, ws, addr, value, name=None, fill=None, fmt=None, bold=False):
        ws[addr] = value
        if fill:
            ws[addr].fill = fill
        if fmt:
            ws[addr].number_format = fmt
        if bold:
            ws[addr].font = HEAD
        if name:
            self.map.setdefault(ws.title, {})[name] = addr
        return addr


def _label_input(c, ws, row, label, value, name, fmt=None, note=None):
    ws[f"A{row}"] = label
    c.put(ws, f"B{row}", value, name, INPUT, fmt)
    if note:
        ws[f"C{row}"] = note


def _label_out(c, ws, row, label, formula, name, fmt=None, note=None):
    ws[f"A{row}"] = label
    c.put(ws, f"B{row}", formula, name, OUT, fmt)
    if note:
        ws[f"C{row}"] = note


def sheet_start(wb, c):
    ws = wb.active
    ws.title = "Start"
    ws["A1"] = "CapKit: what does this money really cost, and which money should I take?"
    ws["A1"].font = TITLE
    lines = [
        "Yellow cells are inputs; green cells are results. Every formula is portable to Google Sheets.",
        "",
        "APR - fixed-debit financing (e.g. a weekly MCA) on its unit-period grid: Reg Z Appendix J APR = IRR x periods per year.",
        "Daily_MCA - a business-day MCA on the calendar-day grid (Appendix J's whole-period case), "
        "with the Federal Reserve holiday calendar.",
        "Loans - term loan and SBA 7(a): payment, APR with fees (RATE), SBA fee on the guaranteed portion and its statutory ceiling.",
        "EarlyPay_Factoring - cost of passing up 2/10 net 30, and invoice factoring cost.",
        "Disclosure - California / New York estimated APR, term and payment for sales-based financing (historical method).",
        "Params_Sources - every rate and limit with its legal source and verified-on date. Holidays - FRB holiday list.",
        "",
        "Not legal, tax or financial advice. An MCA is usually a purchase of receivables, not a loan; its APR is a comparison measure.",
    ]
    for k, t in enumerate(lines, 3):
        ws[f"A{k}"] = t
    ws.column_dimensions["A"].width = 130


def sheet_apr(wb, c):
    ws = wb.create_sheet("APR")
    ws["A1"] = "Fixed-debit financing on its unit-period grid (Appendix J general equation, whole periods)"
    ws["A1"].font = TITLE
    _label_input(c, ws, 3, "Advance (face)", 50000, "advance", USD)
    _label_input(c, ws, 4, "Fees withheld at funding", 0, "fees", USD)
    _label_input(c, ws, 5, "Factor rate (total owed / advance)", 1.35, "factor")
    _label_input(c, ws, 6, "Debit per period", 2250, "payment", USD)
    _label_input(c, ws, 7, "Unit periods per year (52 weekly, 26 biweekly, 12 monthly)", 52, "ppy")
    _label_out(c, ws, 9, "Total owed (purchased amount)", "=B3*B5", "owed", USD)
    _label_out(c, ws, 10, "Net proceeds", "=B3-B4", "net", USD)
    _label_out(c, ws, 11, "Number of debits", "=CEILING(B9/B6-0.000000001,1)", "n")
    _label_out(c, ws, 12, "Finance charge", "=B9-B10", "finance_charge", USD)
    na = '"n/a: schedule longer than the grid"'
    _label_out(c, ws, 13, "APR (Appendix J actuarial)",
               f"=IF(B11<={PERIOD_ROWS},IRR(F3:F{3 + PERIOD_ROWS},0.01)*B7,{na})", "apr", PCT)
    _label_out(c, ws, 14, "Effective annual rate",
               f"=IF(B11<={PERIOD_ROWS},(1+IRR(F3:F{3 + PERIOD_ROWS},0.01))^B7-1,{na})", "ear", PCT)
    _label_out(c, ws, 15, "Simple annualized quote (not an APR)", "=(B9-B10)/B10/(B11/B7)", "simple", PCT,
               "what 'cost / term' calculators show")
    _label_out(c, ws, 16, "Schedule fits in the grid?",
               f'=IF(B11<={PERIOD_ROWS},"OK","TOO LONG: more than {PERIOD_ROWS} debits, APR above is NOT valid")',
               "fits")
    ws["E2"], ws["F2"] = "Period", "Cash flow"
    ws["E2"].font = ws["F2"].font = HEAD
    for k in range(PERIOD_ROWS + 1):
        r = 3 + k
        ws[f"E{r}"] = k
        ws[f"F{r}"] = "=B10" if k == 0 else f"=IF(E{r}<=$B$11,-MIN($B$6,$B$9-$B$6*(E{r}-1)),0)"
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 16


def sheet_daily(wb, c):
    ws = wb.create_sheet("Daily_MCA")
    ws["A1"] = "Business-day MCA on the calendar-day grid: APR = IRR(daily flows) x 365"
    ws["A1"].font = TITLE
    _label_input(c, ws, 3, "Funding date", date(2027, 1, 4), "fund", "yyyy-mm-dd")
    _label_input(c, ws, 4, "Advance (face)", 50000, "advance", USD)
    _label_input(c, ws, 5, "Fees withheld", 0, "fees", USD)
    _label_input(c, ws, 6, "Factor rate", 1.35, "factor")
    _label_input(c, ws, 7, "Debit per business day", 450, "payment", USD)
    _label_input(c, ws, 8, "Skip Federal Reserve holidays? (Y/N)", "Y", "use_holidays")
    dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("B8")
    _label_out(c, ws, 10, "Total owed", "=B4*B6", "owed", USD)
    _label_out(c, ws, 11, "Number of debits", "=CEILING(B10/B7-0.000000001,1)", "n")
    _label_out(c, ws, 12, "Last debit date", f"=INDEX(F3:F{3 + DAILY_ROWS},MATCH(B11,H3:H{3 + DAILY_ROWS},0))",
               "last", "yyyy-mm-dd")
    _label_out(c, ws, 13, "APR (Appendix J: one-day unit period; one debit = single-payment rule)",
               f'=IF(MAX(H3:H{3 + DAILY_ROWS})<B11,"n/a: schedule longer than the grid",'
               f'IF(B11=1,IF(EDATE(B3,ROUND((B12-B3)/30.4,0))=B12,12/ROUND((B12-B3)/30.4,0),365/(B12-B3))'
               f'*(B10/(B4-B5)-1),IRR(I3:I{3 + DAILY_ROWS},0.001)*365))', "apr", PCT)
    _label_out(c, ws, 15, "Schedule fits in the grid?",
               f'=IF(MAX(H3:H{3 + DAILY_ROWS})>=B11,"OK","TOO LONG: schedule exceeds {DAILY_ROWS} days, APR is NOT valid")',
               "fits")
    _label_out(c, ws, 14, "Business-day rate x 252 (NOT an Appendix J figure)",
               f"=IRR(J3:J{3 + DAILY_ROWS},0.001)*252", "bd252", PCT, "shown for contrast only")
    for k, h in zip("EFGHIJ", ["Day", "Date", "Debit day?", "Debits so far", "Cash flow", "Business-day flow"]):
        ws[f"{k}2"] = h
        ws[f"{k}2"].font = HEAD
    hol = f"Holidays!$A$2:$A${1 + len(_holiday_list())}"
    for k in range(DAILY_ROWS + 1):
        r = 3 + k
        ws[f"E{r}"] = k
        ws[f"F{r}"] = f"=$B$3+E{r}"
        ws[f"F{r}"].number_format = "yyyy-mm-dd"
        if k == 0:
            ws[f"G{r}"] = 0
            ws[f"H{r}"] = 0
            ws[f"I{r}"] = "=B4-B5"
            ws[f"J{r}"] = "=B4-B5"
        else:
            ws[f"G{r}"] = f'=IF(AND(WEEKDAY(F{r},2)<=5,OR($B$8="N",COUNTIF({hol},F{r})=0)),1,0)'
            ws[f"H{r}"] = f"=H{r - 1}+G{r}"
            ws[f"I{r}"] = f"=IF(AND(G{r}=1,H{r}<=$B$11),-MIN($B$7,$B$10-$B$7*(H{r}-1)),0)"
    # business-day grid (each debit is one period): row k = k-th debit
    for k in range(DAILY_ROWS + 1):
        r = 3 + k
        if k:
            ws[f"J{r}"] = f"=IF(E{r}<=$B$11,-MIN($B$7,$B$10-$B$7*(E{r}-1)),0)"
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["F"].width = 12


def sheet_loans(wb, c):
    ws = wb.create_sheet("Loans")
    ws["A1"] = "Term loan and SBA 7(a)"
    ws["A1"].font = TITLE
    _label_input(c, ws, 3, "Term loan amount", 50000, "tl_amount", USD)
    _label_input(c, ws, 4, "Note rate (annual)", 0.15, "tl_rate", PCT)
    _label_input(c, ws, 5, "Term (months)", 24, "tl_months")
    _label_input(c, ws, 6, "Fee withheld", 1500, "tl_fee", USD)
    _label_out(c, ws, 7, "Monthly payment (billed in cents)", "=ROUND(PMT(B4/12,B5,-B3),2)", "tl_payment", USD)
    _label_out(c, ws, 10, "Final payment (absorbs rounding)", "=ROUND(FV(B4/12,B5-1,B7,-B3)*(1+B4/12),2)",
               "tl_final", USD)
    _label_out(c, ws, 8, "APR (Appendix J, monthly unit)",
               f'=IF(B5<={LOAN_ROWS},IRR(O3:O{3 + LOAN_ROWS},0.01)*12,"n/a: term longer than the grid")', "tl_apr", PCT)
    _label_out(c, ws, 9, "Finance charge", "=B7*(B5-1)+B10-(B3-B6)", "tl_fc", USD)

    ws["A11"] = "SBA 7(a) (variable rate held at today's Prime)"
    ws["A11"].font = HEAD
    _label_input(c, ws, 12, "Loan amount", 42548.02, "sba_amount", USD)
    _label_input(c, ws, 13, "Prime rate", P.param("prime_rate"), "prime", PCT, "placeholder - update from FRED DPRIME")
    _label_input(c, ws, 14, "Spread over Prime (blank = SOP 50 10 maximum)", None, "sba_spread_in", PCT)
    _label_input(c, ws, 15, "Term (months)", 120, "sba_months")
    _label_input(c, ws, 16, "Fee rate on guaranteed portion (blank = FY2026/FY2027 table)", None, "sba_fee_in", PCT)
    _label_out(c, ws, 17, "Maximum spread for this size", "=INDEX($F$4:$F$7,MATCH(B12,$E$4:$E$7,1))",
               "sba_max_spread", PCT)
    _label_out(c, ws, 18, "Rate", '=B13+IF(B14="",B17,B14)', "sba_rate", PCT)
    _label_out(c, ws, 19, "Guaranty share", "=IF(B12<=150000,0.85,0.75)", "sba_share", PCT)
    _label_out(c, ws, 20, "Fee rate on guaranteed portion",
               '=IF(B16="",INDEX($I$4:$I$6,MATCH(B12,$H$4:$H$6,1)),B16)', "sba_fee_rate", PCT)
    _label_out(c, ws, 21, "Upfront guaranty fee",
               '=IF(B16<>"",B16*B19*B12,IF(B15<=12,0.0025*B19*B12,IF(B12<=700000,B20*B19*B12,'
               '0.035*MIN(B19*B12,1000000)+0.0375*MAX(0,B19*B12-1000000))))', "sba_fee", USD,
               "FY2026/FY2027 standard rates (identical); 0.25% if 12 months or less; 0% tiers not applied")
    _label_out(c, ws, 22, "Statutory fee ceiling",
               "=B19*B12*INDEX($L$4:$L$6,MATCH(B12,$K$4:$K$6,1))+MAX(0,B19*B12-1000000)*0.0025",
               "sba_ceiling", USD)
    _label_out(c, ws, 23, "Fee within ceiling?", '=IF(B21<=B22+0.000001,"OK","ABOVE STATUTORY CEILING")', "sba_fee_ok")
    _label_out(c, ws, 24, "Monthly payment (billed in cents)", "=ROUND(PMT(B18/12,B15,-B12),2)", "sba_payment", USD)
    _label_out(c, ws, 26, "Final payment (absorbs rounding)", "=ROUND(FV(B18/12,B15-1,B24,-B12)*(1+B18/12),2)",
               "sba_final", USD)
    _label_out(c, ws, 25, "APR with fee (monthly unit)",
               f'=IF(B15<={LOAN_ROWS},IRR(Q3:Q{3 + LOAN_ROWS},0.01)*12,"n/a: term longer than the grid")', "sba_apr", PCT)
    ws["N2"], ws["O2"], ws["Q2"] = "Month", "Term loan flow", "SBA flow"
    for k in range(LOAN_ROWS + 1):
        r = 3 + k
        ws[f"N{r}"] = k
        if k == 0:
            ws[f"O{r}"], ws[f"Q{r}"] = "=B3-B6", "=B12-B21"
        else:
            ws[f"O{r}"] = f"=IF(N{r}<$B$5,-$B$7,IF(N{r}=$B$5,-$B$10,0))"
            ws[f"Q{r}"] = f"=IF(N{r}<$B$15,-$B$24,IF(N{r}=$B$15,-$B$26,0))"

    ws["E3"], ws["F3"] = "Loan from ($)", "Max spread"
    ws["H3"], ws["I3"] = "Loan from ($)", "FY fee rate"
    ws["K3"], ws["L3"] = "Loan from ($)", "Fee ceiling"

    def table(c1, c2, rows):
        lo = 0.0
        for k, (b, v) in enumerate(rows):
            ws[f"{c1}{4 + k}"], ws[f"{c2}{4 + k}"] = lo, v       # applies from `lo` (exclusive of the
            lo = round(b + 0.01, 2) if math.isfinite(b) else lo   # previous bound) up to this row's bound
    table("E", "F", P.param("sba_max_spread"))
    table("H", "I", P.param("sba_fee_fy")[2027]["tiers"])
    table("K", "L", P.param("sba_fee_ceiling"))
    ws["E9"] = "Sources: SOP 50 10 8; SBA FY fee notice; 15 U.S.C. 636(a)(18)(A). Verify each year."
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 16


def sheet_earlypay(wb, c):
    ws = wb.create_sheet("EarlyPay_Factoring")
    ws["A1"] = "Supplier terms and invoice factoring"
    ws["A1"].font = TITLE
    _label_input(c, ws, 3, "Discount (e.g. 2%)", 0.02, "disc", PCT)
    _label_input(c, ws, 4, "Discount days", 10, "dd")
    _label_input(c, ws, 5, "Net days", 30, "nd")
    _label_out(c, ws, 6, "Cost of forgoing the discount - nominal", "=B3/(1-B3)*365/(B5-B4)", "ep_nominal", PCT)
    _label_out(c, ws, 7, "Cost of forgoing the discount - effective", "=(1+B3/(1-B3))^(365/(B5-B4))-1", "ep_effective", PCT)
    _label_input(c, ws, 9, "Invoice face", 10000, "face", USD)
    _label_input(c, ws, 10, "Advance rate", 0.8, "adv_rate", PCT)
    _label_input(c, ws, 11, "Fee per 30 days (or part)", 0.03, "fee30", PCT)
    _label_input(c, ws, 12, "Days until the customer pays", 45, "days")
    _label_out(c, ws, 13, "Advance", "=B9*B10", "fac_adv", USD)
    _label_out(c, ws, 14, "Fee", "=B11*B9*CEILING(B12/30,1)", "fac_fee", USD)
    _label_out(c, ws, 15, "Rebate at collection", "=B9-B13-B14", "fac_rebate", USD)
    _label_input(c, ws, 17, "Sale date", date(2027, 1, 4), "sale_date", "yyyy-mm-dd")
    _label_out(c, ws, 16, "APR (Appendix J single payment: term is the unit-period)",
               "=IF(EDATE(B17,ROUND(B12/30.4,0))=B17+B12,12/ROUND(B12/30.4,0),365/B12)*(B14/B13)",
               "fac_apr", PCT, "valid for terms under one year")
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 16


def sheet_disclosure(wb, c):
    ws = wb.create_sheet("Disclosure")
    ws["A1"] = "CA / NY estimated APR for sales-based financing - historical method"
    ws["A1"].font = TITLE
    ws["A2"] = ("10 CCR 930/940/942 and 23 NYCRR 600.3/600.7/600.8. Monthly sales are spread evenly over the business "
                "days in the 12 months after funding (CapKit's stated assumption). Not a compliance certification.")
    _label_input(c, ws, 4, "Funding provided", 50000, "funding", USD)
    _label_input(c, ws, 5, "Total amount owed", 67500, "owed", USD)
    _label_input(c, ws, 6, "Prepaid fees", 0, "fees", USD)
    _label_input(c, ws, 7, "Split rate (holdback)", 0.10, "split", PCT)
    _label_input(c, ws, 8, "Averaging window (4-12 months)", 6, "window")
    _label_input(c, ws, 9, "Funding date", date(2027, 1, 4), "fund", "yyyy-mm-dd")
    _label_input(c, ws, 10, "Contractual minimum debit", 0, "minpay", USD)
    _label_input(c, ws, 11, "Disclosed estimated APR (to check)", 0.68, "disclosed", PCT)
    ws["E3"], ws["F3"] = "Month (oldest=1)", "Monthly sales"
    sales = [60000, 58000, 62000, 61000, 59000, 60000, 57000, 63000, 61000, 60000, 59000, 61000]
    for k in range(12):
        ws[f"E{4 + k}"] = k + 1
        c.put(ws, f"F{4 + k}", sales[k], f"sales{k + 1}", INPUT, USD)
    _label_out(c, ws, 13, "Window valid?", '=IF(AND(B8>=4,B8<=12),"OK","window must be 4-12 months")', "window_ok")
    _label_out(c, ws, 14, "Historical average monthly sales", "=SUMPRODUCT((E4:E15>12-B8)*F4:F15)/B8", "avg", USD)
    hol = f"Holidays!$A$2:$A${1 + len(_holiday_list())}"
    _label_out(c, ws, 15, "Business days in the 12 months after funding",
               f"=SUMPRODUCT((I4:I{4 + DAILY_ROWS}>B9)*(I4:I{4 + DAILY_ROWS}<=EDATE(B9,12))*J4:J{4 + DAILY_ROWS})",
               "nbd")
    _label_out(c, ws, 16, "Estimated payment per business day", "=MAX(B7*B14*12/B15,B10)", "payment", USD)
    _label_out(c, ws, 17, "Number of payments", "=CEILING(B5/B16-0.000000001,1)", "n")
    _label_out(c, ws, 18, "Last payment date", f"=INDEX(I4:I{4 + DAILY_ROWS},MATCH(B17,K4:K{4 + DAILY_ROWS},0))",
               "last", "yyyy-mm-dd")
    _label_out(c, ws, 19, "Estimated term (days)", "=B18-B9", "term_days")
    _label_out(c, ws, 20, "Estimated term (months, days / 30.4)", "=ROUND(B19/30.4,1)", "term_months")
    _label_out(c, ws, 21, "Finance charge", "=B5-B4", "fc", USD)
    _label_out(c, ws, 22, "Estimated monthly cost", "=B5/(B19/30.4)", "monthly_cost", USD)
    _label_out(c, ws, 23, "Estimated APR (actuarial)",
               f'=IF(MAX(K4:K{4 + DAILY_ROWS})<B17,"n/a: term longer than the grid",IRR(L4:L{4 + DAILY_ROWS},0.001)*365)',
               "apr", PCT)
    _label_out(c, ws, 24, "Disclosed APR within tolerance of actuarial? (CA 955 / NY 600.4)",
               '=IF(OR(ABS(B11-B23)<=0.00125,AND(B11>0,(B23-B11)/B11<=0.025)),"yes","no")', "check",
               "1/8 point, or a signed percentage difference of 2.5% or less; U.S. Rule figure: see the engine")
    _label_out(c, ws, 26, "Schedule fits in the grid?",
               f'=IF(MAX(K4:K{4 + DAILY_ROWS})>=B17,"OK","TOO LONG: term exceeds {DAILY_ROWS} days, figures are NOT valid")',
               "fits")
    ws["A25"] = "The U.S. Rule figure (also permitted) is computed by the engine; see the disclosure skill."
    for k, h in zip("HIJKL", ["Day", "Date", "Debit day?", "Debits so far", "Cash flow"]):
        ws[f"{k}3"] = h
        ws[f"{k}3"].font = HEAD
    for k in range(DAILY_ROWS + 1):
        r = 4 + k
        ws[f"H{r}"] = k
        ws[f"I{r}"] = f"=$B$9+H{r}"
        ws[f"I{r}"].number_format = "yyyy-mm-dd"
        if k == 0:
            ws[f"J{r}"], ws[f"K{r}"], ws[f"L{r}"] = 0, 0, "=B4"
        else:
            ws[f"J{r}"] = f"=IF(AND(WEEKDAY(I{r},2)<=5,COUNTIF({hol},I{r})=0),1,0)"
            ws[f"K{r}"] = f"=K{r - 1}+J{r}"
            ws[f"L{r}"] = f"=IF(AND(J{r}=1,K{r}<=$B$17),-MIN($B$16,$B$5-$B$16*(K{r}-1)),0)"
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 16


def _holiday_list():
    out = []
    for y in range(2025, 2041):
        out += sorted(frb_holidays(y))
    return out


def sheet_params(wb, c):
    ws = wb.create_sheet("Params_Sources")
    heads = ["Key", "Value", "Unit", "Description", "Source", "Verified on", "Status"]
    for k, h in enumerate(heads, 1):
        ws.cell(row=1, column=k, value=h).font = HEAD
    for r, (key, e) in enumerate(P.PARAMS.items(), 2):
        v = e["value"]
        ws.cell(row=r, column=1, value=key)
        ws.cell(row=r, column=2, value=v if isinstance(v, (int, float)) else json.dumps(v, default=str))
        ws.cell(row=r, column=3, value=e["unit"])
        ws.cell(row=r, column=4, value=e["desc"])
        ws.cell(row=r, column=5, value=e["source"])
        ws.cell(row=r, column=6, value=e["verified_on"])
        ws.cell(row=r, column=7, value=e["status"])
    for k, w in zip("ABCDEFG", (28, 30, 22, 80, 50, 12, 12)):
        ws.column_dimensions[k].width = w
    hs = wb.create_sheet("Holidays")
    hs["A1"] = "Federal Reserve holidays (Sunday -> Monday; Saturday holidays not observed)"
    hs["A1"].font = HEAD
    for r, d in enumerate(_holiday_list(), 2):
        hs[f"A{r}"] = d
        hs[f"A{r}"].number_format = "yyyy-mm-dd"


def build_workbook(path="workbook/CapKit.xlsx", cells_path=None):
    """Write the workbook and a cells.json map of named cells (used by the verifier)."""
    c = Cells()
    wb = Workbook()
    sheet_start(wb, c)
    sheet_apr(wb, c)
    sheet_daily(wb, c)
    sheet_loans(wb, c)
    sheet_earlypay(wb, c)
    sheet_disclosure(wb, c)
    sheet_params(wb, c)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    cells_path = Path(cells_path) if cells_path else path.with_suffix(".cells.json")
    cells_path.write_text(json.dumps(c.map, indent=1, sort_keys=True))
    return path
