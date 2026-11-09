"""CSV export with spreadsheet formula injection protection for user-controlled fields."""

import csv
from io import StringIO


def _safe_cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str):
        return value
    # Spreadsheet apps may interpret cells beginning with these characters as formulas,
    # even after whitespace or control characters.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def encode_csv(rows: list[dict], columns: tuple[str, ...]) -> str:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_safe_cell(row.get(name)) for name in columns])
    return buffer.getvalue()
