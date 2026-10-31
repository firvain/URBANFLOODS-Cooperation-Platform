"""CSV cell formatting shared by the CSV exports (admin stats, FAIR posts export).

Spreadsheet apps treat a cell starting with ``=``, ``+``, ``-``, ``@``, tab or carriage return
as a formula (CSV injection), so such cells get a leading apostrophe.
"""

from __future__ import annotations

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: object) -> str:
    """``value`` as a safe CSV cell: booleans as ``true``/``false``, ``None`` as empty,
    formula-like text prefixed with ``'``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    return f"'{text}" if text.startswith(CSV_FORMULA_PREFIXES) else text
