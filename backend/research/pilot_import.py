"""Import pilot measurements from an Excel (.xlsx) or CSV file: read, preview, then a person confirms.

Two layouts are understood:
  long  - one row per reading:   Date | Metric | Value | (Phase)
  wide  - one column per metric: Date | Hours per week | Errors per week | (Phase)

Phase comes from a Phase column when there is one, otherwise from the date: before the pilot's start
date is baseline, from the start date on is pilot. Rows that can't be used are listed with the reason,
never guessed. Everything here is plain code: no AI.

Excel files are read with the standard library (an .xlsx file is a zip of XML parts), so no extra
package is needed. Files with a DOCTYPE are refused (protection against XML entity tricks).
"""
import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_UNZIPPED = 20 * 1024 * 1024
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
PHASES = {"baseline": "baseline", "before": "baseline", "pre": "baseline", "pre-pilot": "baseline",
          "pilot": "pilot", "after": "pilot", "during": "pilot", "trial": "pilot"}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class ImportProblem(ValueError):
    pass


# ── Reading the file into rows of cells ──────────────────────────────────────

def read_table(filename: str, data: bytes) -> list[list]:
    if len(data) > MAX_BYTES:
        raise ImportProblem("The file is larger than 2 MB")
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        rows = read_xlsx(data)
    elif name.endswith(".csv") or name.endswith(".txt"):
        rows = read_csv(data)
    else:
        raise ImportProblem("Use an Excel (.xlsx) or CSV file. For older .xls files, save as .xlsx first")
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if len(rows) < 2:
        raise ImportProblem("The file needs a header row and at least one row of readings")
    if len(rows) > MAX_ROWS + 1:
        raise ImportProblem(f"The file has more than {MAX_ROWS} rows")
    return rows


def read_csv(data: bytes) -> list[list]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def read_xlsx(data: bytes) -> list[list]:
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportProblem("This doesn't look like an Excel file")
    if sum(item.file_size for item in book.infolist()) > MAX_UNZIPPED:
        raise ImportProblem("The Excel file is too large once unpacked")

    def xml(part):
        raw = book.read(part)
        if b"<!DOCTYPE" in raw[:2000].upper():
            raise ImportProblem("The Excel file contains content that isn't allowed")
        return ElementTree.fromstring(raw)

    try:
        workbook = xml("xl/workbook.xml")
        first = workbook.find("m:sheets/m:sheet", NS)
        rel_id = first.get(f"{{{NS['r']}}}id")
        rels = xml("xl/_rels/workbook.xml.rels")
        target = next(r.get("Target") for r in rels.findall("rel:Relationship", NS) if r.get("Id") == rel_id)
        sheet = xml("xl/" + target.lstrip("/").removeprefix("xl/"))
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
                      for si in xml("xl/sharedStrings.xml").findall("m:si", NS)]
    except (KeyError, StopIteration, AttributeError, ElementTree.ParseError):
        raise ImportProblem("Couldn't read the first sheet of this Excel file")

    rows = []
    for row in sheet.iter(f"{{{NS['m']}}}row"):
        cells = {}
        for cell in row.findall("m:c", NS):
            column = column_index(cell.get("r", ""))
            kind, value = cell.get("t"), cell.find("m:v", NS)
            if kind == "s" and value is not None:
                cells[column] = shared[int(value.text)]
            elif kind == "inlineStr":
                cells[column] = "".join(t.text or "" for t in cell.iter(f"{{{NS['m']}}}t"))
            elif value is not None and value.text is not None:
                cells[column] = value.text if kind in ("str", "b", "e") else float(value.text)
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        if len(rows) > MAX_ROWS + 1:
            break
    return rows


def column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    index = 0
    for letter in letters.group(0) if letters else "A":
        index = index * 26 + ord(letter) - 64
    return index - 1


# ── Understanding the cells ──────────────────────────────────────────────────

def parse_date(cell) -> date | None:
    """ISO dates, day-first dates (UAE style: 03/11/2026 = 3 November), '3 Nov 2026', or Excel date numbers."""
    if isinstance(cell, float):
        return date(1899, 12, 30) + timedelta(days=int(cell)) if 20000 < cell < 80000 else None
    text = str(cell).strip()
    if re.fullmatch(r"\d{5}(\.0+)?", text):
        return parse_date(float(text))
    for pattern in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        try:
            return date(year + 2000 if year < 100 else year, month, day)
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})[ -]([A-Za-z]{3})[a-z]*[ -,]*(\d{4})", text)
    if match and match.group(2).lower() in MONTHS:
        try:
            return date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1)))
        except ValueError:
            return None
    return None


def parse_number(cell) -> float | None:
    if isinstance(cell, float):
        return cell
    text = str(cell).strip().replace(" ", "").replace(" ", "")
    if re.fullmatch(r"-?\d+,\d+", text):            # 1,5 written with a decimal comma
        text = text.replace(",", ".")
    text = text.replace(",", "")                      # 1,200 thousands separator
    try:
        return float(text)
    except ValueError:
        return None


def normalise(text) -> str:
    text = re.sub(r"\([^)]*\)", "", str(text))         # "Hours per week (hours)" → "Hours per week"
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def match_metric(header, criteria: list[dict]) -> dict | None:
    wanted = normalise(header)
    for criterion in criteria:
        if wanted and wanted in (criterion["key"], normalise(criterion["metric"])):
            return criterion
    return None


def find_column(headers: list[str], *names) -> int | None:
    for index, header in enumerate(headers):
        h = normalise(header)
        if h in names or any(h.startswith(name) for name in names if name == "date"):
            return index
    return None


# ── Preview ──────────────────────────────────────────────────────────────────

def preview(rows: list[list], criteria: list[dict], start_date: date, running: bool, existing: list[dict]) -> dict:
    headers = [str(h).strip() for h in rows[0]]
    date_col = find_column(headers, "date", "day", "measured_on", "reading_date")
    phase_col = find_column(headers, "phase", "stage", "period")
    metric_col, value_col = find_column(headers, "metric", "measure", "kpi"), find_column(headers, "value", "reading", "result")
    if date_col is None:
        raise ImportProblem("Add a Date column so readings can be placed in time")
    long_layout = metric_col is not None and value_col is not None
    columns = []
    if not long_layout:
        for index, header in enumerate(headers):
            if index in (date_col, phase_col):
                continue
            criterion = match_metric(header, criteria)
            columns.append({"index": index, "header": header, "metric": criterion["metric"] if criterion else None,
                            "key": criterion["key"] if criterion else None})
        if not any(c["key"] for c in columns):
            raise ImportProblem("No column matches the pilot's metrics: "
                                + ", ".join(c["metric"] for c in criteria) + ". Rename a column to match")

    readings, empty = [], 0
    for number, row in enumerate(rows[1:], start=2):
        cell = lambda i: row[i] if i is not None and i < len(row) else ""
        when, phase_text = parse_date(cell(date_col)), str(cell(phase_col)).strip().lower()
        if long_layout:
            criterion = match_metric(cell(metric_col), criteria)
            pairs = [(criterion, str(cell(metric_col)).strip(), cell(value_col))]
        else:
            pairs = [(match_metric(c["header"], criteria), c["header"], cell(c["index"])) for c in columns if c["key"]]
        for criterion, label, raw in pairs:
            if str(raw).strip() == "":
                empty += 1
                continue
            readings.append(check({"row": number, "metric": criterion["key"] if criterion else None,
                                   "metric_name": criterion["metric"] if criterion else label,
                                   "date": when, "value": parse_number(raw), "phase_text": phase_text,
                                   "raw_date": str(cell(date_col))}, start_date))
    mark(readings, running, existing)
    ok = [r for r in readings if not r["problem"]]
    return {"layout": "one row per reading" if long_layout else "one column per metric",
            "columns": columns, "start_date": start_date.isoformat(), "rows": [public(r) for r in readings],
            "ready": len(ok), "skipped": len(readings) - len(ok), "empty_cells": empty,
            "baseline": sum(r["phase"] == "baseline" for r in ok), "pilot": sum(r["phase"] == "pilot" for r in ok)}


def check(reading: dict, start_date: date) -> dict:
    reading["problem"] = None
    if reading["metric"] is None:
        reading["problem"] = f"“{reading['metric_name']}” isn't one of the pilot's metrics"
    elif reading["date"] is None:
        reading["problem"] = f"Can't read the date “{reading['raw_date']}”"
    elif reading["value"] is None:
        reading["problem"] = "The value isn't a number"
    phase = PHASES.get(reading.pop("phase_text"), None)
    if reading["date"] and phase is None:
        phase = "baseline" if reading["date"] < start_date else "pilot"
    reading["phase"] = phase
    return reading


def mark(readings: list[dict], running: bool, existing: list[dict]):
    """Duplicates (already logged, or twice in the file) and pilot readings before the pilot started."""
    seen = {(m["metric"], m["phase"], str(m["date"]), float(m["value"])) for m in existing}
    for r in readings:
        if r["problem"]:
            continue
        key = (r["metric"], r["phase"], r["date"].isoformat(), float(r["value"]))
        if r["phase"] == "pilot" and not running:
            r["problem"] = "Pilot readings can be imported once the pilot is running"
        elif key in seen:
            r["problem"] = "Already logged"
        seen.add(key)


def public(r: dict) -> dict:
    return {"row": r["row"], "metric": r["metric"], "metric_name": r["metric_name"], "phase": r["phase"],
            "date": r["date"].isoformat() if r["date"] else None, "value": r["value"], "problem": r["problem"]}
