"""Dates, working days and calendar invites (.ics) for the UAE.

The UAE weekend is Saturday and Sunday, and Dubai time is UTC+4 all year (no daylight saving).
An .ics file is the standard calendar format: Outlook, Teams, Google Calendar and Apple
Calendar all open it.
"""
import re
from datetime import date, datetime, timedelta, timezone

DUBAI = timezone(timedelta(hours=4), "GST")
WEEKEND = {5, 6}  # Saturday, Sunday


def today() -> date:
    return datetime.now(DUBAI).date()


def now_local() -> datetime:
    return datetime.now(DUBAI).replace(tzinfo=None)


def add_working_days(start: date, days: int) -> date:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() not in WEEKEND:
            days -= 1
    return current


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_due(text: str, reference: date) -> date | None:
    """Turn a written deadline like "28 October" or "2026-11-03" into a date, when it's unambiguous.
    Vague ones ("next week", "soon") stay undated rather than guessed."""
    if not text:
        return None
    text = text.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\b(?:\s+(\d{4}))?", text) or \
        re.search(r"\b([A-Za-z]{3})[a-z]*\s+(\d{1,2})\b(?:,?\s+(\d{4}))?", text)
    if not match:
        return None
    first, second, year = match.groups()
    day, month = (first, second) if first.isdigit() else (second, first)
    month_number = MONTHS.get(month[:3].lower())
    if not month_number:
        return None
    try:
        result = date(int(year) if year else reference.year, month_number, int(day))
    except ValueError:
        return None
    if not year and result < reference - timedelta(days=60):   # "5 January" said in December means next year
        result = result.replace(year=result.year + 1)
    return result


def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar lines must be at most 75 octets; longer ones continue on the next line after a space."""
    out, current = [], ""
    for char in line:
        if len((current + char).encode()) > 74:
            out.append(current)
            current = " " + char
        else:
            current += char
    out.append(current)
    return "\r\n".join(out)


def invite_ics(meeting: dict) -> str:
    start = datetime.fromisoformat(meeting["start_at"])
    end = start + timedelta(minutes=meeting.get("duration_min") or 45)
    agenda = (meeting.get("plan") or {}).get("agenda", [])
    description = "Agenda:\n" + "\n".join(f"- {a['item']} ({a['minutes']} min)" for a in agenda)
    if meeting.get("teams_link"):
        description = f"Join Microsoft Teams meeting: {meeting['teams_link']}\n\n" + description
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Innovation Hub//Meetings//EN", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VTIMEZONE", "TZID:Asia/Dubai", "BEGIN:STANDARD", "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0400", "TZOFFSETTO:+0400", "TZNAME:GST", "END:STANDARD", "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:meeting-{meeting['id']}@innovation-hub",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID=Asia/Dubai:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID=Asia/Dubai:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{_escape(meeting['title'])}",
        f"DESCRIPTION:{_escape(description)}",
        f"LOCATION:{_escape(meeting.get('teams_link') or 'Microsoft Teams')}",
        "BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "DESCRIPTION:Reminder", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
