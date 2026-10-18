"""Importing pilot measurements from Excel or CSV: preview first, nothing saved until a person confirms."""
import io
import zipfile
from xml.sax.saxutils import escape

from backend.research import pilot_import
from test_pilot import call, log, pilot_planning, running, setup

# The pilot in test_pilot starts on 2026-11-01: earlier dates are baseline, later ones pilot.


def preview(client, sid, name, content):
    return client.post(f"/api/submissions/{sid}/pilot/import/preview", files={"file": (name, content)})


def confirm(client, sid, result, name="readings.csv"):
    rows = [{k: r[k] for k in ("metric", "phase", "value", "date")} for r in result["rows"] if not r["problem"]]
    return client.post(f"/api/submissions/{sid}/pilot/import", json={"file_name": name, "rows": rows})


def xlsx(rows) -> bytes:
    """A minimal real .xlsx: text as inline strings, numbers as numbers (dates as Excel day numbers)."""
    def cell(ref, value):
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
    sheet = "".join(f'<row r="{i}">' + "".join(cell(f"{chr(65 + j)}{i}", v) for j, v in enumerate(row) if v != "")
                    + "</row>" for i, row in enumerate(rows, start=1))
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
                                      '<sheet name="Readings" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{main}"><sheetData>{sheet}</sheetData></worksheet>')
    return buffer.getvalue()


def planned(client):
    sid = pilot_planning(client)
    setup(client, sid)
    return sid


def test_wide_csv_with_phase_taken_from_the_start_date(client):
    sid = planned(client)
    csv = ("Date,Hours per week (hours),Errors per week,Comments\n"
           "2026-10-20,6,4,quiet week\n21/10/2026,6.5,3,\n22 Oct 2026,5.5,,\n").encode()
    result = preview(client, sid, "baseline.csv", csv).json()
    assert result["layout"] == "one column per metric" and result["ready"] == 5 and result["empty_cells"] == 1
    assert result["baseline"] == 5 and result["pilot"] == 0
    assert [c["key"] for c in result["columns"]] == ["hours_per_week", "errors_per_week", None]   # Comments ignored
    assert {r["date"] for r in result["rows"]} == {"2026-10-20", "2026-10-21", "2026-10-22"}     # 21/10 read day-first
    assert not client.get(f"/api/submissions/{sid}").json()["research"]["pilot"].get("measurements")  # nothing saved yet
    record = confirm(client, sid, result).json()
    measurements = record["research"]["pilot"]["measurements"]
    assert len(measurements) == 5 and measurements[0]["note"] == "Imported from readings.csv"
    assert call(client, sid, "start").json()["status"] == "Pilot running"      # the baseline gate is satisfied


def test_long_excel_file_with_excel_dates_and_a_phase_column(client):
    sid = running(client)
    nov_3 = 46329                                     # Excel's day number for 2026-11-03
    content = xlsx([["Date", "Metric", "Value", "Phase"],
                    [nov_3, "Hours per week", 1.5, "Pilot"],
                    [nov_3 + 7, "hours_per_week", 1.8, "pilot"],
                    ["2026-11-17", "Errors per week", 0, "after"]])
    result = preview(client, sid, "pilot.xlsx", content).json()
    assert result["layout"] == "one row per reading" and result["ready"] == 3 and result["pilot"] == 3
    assert result["rows"][0]["date"] == "2026-11-03"
    assert confirm(client, sid, result, "pilot.xlsx").status_code == 200


def test_problem_rows_are_listed_not_guessed(client):
    sid = running(client)
    csv = ("Date;Metric;Value\n"
           "2026-11-05;Hours per week;1,5\n"            # decimal comma, semicolon file: fine
           "31/02/2026;Hours per week;2\n"              # impossible date
           "2026-11-06;Coffee cups;4\n"                 # not a pilot metric
           "2026-11-07;Errors per week;lots\n"          # not a number
           "2026-11-05;Hours per week;1,5\n").encode()  # same reading twice
    rows = preview(client, sid, "mixed.csv", csv).json()["rows"]
    problems = [r["problem"] for r in rows]
    assert problems[0] is None and rows[0]["value"] == 1.5
    assert "date" in problems[1] and "isn't one of the pilot's metrics" in problems[2]
    assert "number" in problems[3] and problems[4] == "Already logged"


def test_readings_already_logged_are_skipped(client):
    sid = running(client)
    log(client, sid, "hours_per_week", "pilot", 1.5)       # logged by hand for 2026-11-01
    csv = b"Date,Hours per week\n2026-11-01,1.5\n2026-11-08,1.7\n"
    result = preview(client, sid, "again.csv", csv).json()
    assert [r["problem"] for r in result["rows"]] == ["Already logged", None]


def test_pilot_readings_wait_until_the_pilot_is_running(client):
    sid = planned(client)
    result = preview(client, sid, "early.csv", b"Date,Hours per week\n2026-10-25,6\n2026-11-04,2\n").json()
    assert result["rows"][1]["problem"] == "Pilot readings can be imported once the pilot is running"
    sneaky = client.post(f"/api/submissions/{sid}/pilot/import", json={"file_name": "x.csv", "rows": [
        {"metric": "hours_per_week", "phase": "baseline", "value": 6, "date": "2026-10-25"},
        {"metric": "hours_per_week", "phase": "pilot", "value": 2, "date": "2026-11-04"}]})
    assert sneaky.status_code == 422 and "Nothing imported" in sneaky.json()["detail"]
    assert not client.get(f"/api/submissions/{sid}").json()["research"]["pilot"].get("measurements")   # all or nothing


def test_files_that_cant_be_used(client):
    sid = planned(client)
    assert "Excel (.xlsx) or CSV" in preview(client, sid, "old.xls", b"x").json()["detail"]
    assert "Date column" in preview(client, sid, "a.csv", b"Hours per week\n6\n").json()["detail"]
    assert "No column matches" in preview(client, sid, "a.csv", b"Date,Coffee\n2026-10-20,3\n").json()["detail"]
    assert "Excel file" in preview(client, sid, "fake.xlsx", b"not a zip").json()["detail"]
    big = b"Date,Hours per week\n" + b"2026-10-20,6\n" * 200_000
    assert "2 MB" in preview(client, sid, "big.csv", big).json()["detail"]


def test_import_needs_an_agreed_setup(client):
    sid = pilot_planning(client)
    assert preview(client, sid, "a.csv", b"Date,Hours per week\n2026-10-20,6\n").status_code == 409


def test_excel_with_a_doctype_is_refused():
    content = xlsx([["Date", "Hours per week"], ["2026-10-20", 6]])
    with zipfile.ZipFile(io.BytesIO(content)) as source, io.BytesIO() as out:
        with zipfile.ZipFile(out, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    data = b'<!DOCTYPE x [<!ENTITY a "aaaa">]>' + data
                target.writestr(item, data)
        try:
            pilot_import.read_table("evil.xlsx", out.getvalue())
            assert False, "should have been refused"
        except pilot_import.ImportProblem as problem:
            assert "isn't allowed" in str(problem)
