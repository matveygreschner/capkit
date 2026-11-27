"""Live data: the current Bank Prime Loan Rate and SOFR from FRED (public CSV, no API key)."""
from __future__ import annotations

import csv
import io
import urllib.request

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def latest(series: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(FRED.format(series=series), headers={"User-Agent": "capkit"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        rows = list(csv.reader(io.StringIO(r.read().decode())))
    for d, v in reversed(rows[1:]):
        if v not in (".", ""):
            return {"series": series, "date": d, "value": float(v) / 100, "source": FRED.format(series=series)}
    raise ValueError(f"no observations for {series}")


def prime_rate() -> dict:
    return latest("DPRIME")


def sofr() -> dict:
    return latest("SOFR")
