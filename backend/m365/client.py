"""Microsoft 365: send email, read replies, book Teams meetings and fetch meeting transcripts.

Two versions behind one interface:
  DemoM365   - a pretend mailbox and calendar stored in the Hub's own database. Fictional replies and
               recaps, clearly labelled DEMO. Used now (HUB_M365=demo, the default).
  GraphM365  - the real thing, through Microsoft Graph, acting as the signed-in employee. Switched on
               with HUB_M365=graph once Khazna IT registers the app in Microsoft Entra ID and grants
               consent (see docs/microsoft-365.md). Not yet run against a real tenant.

Nothing here decides to send anything: the routes call send_mail only after a person approved that email.
"""
import os
import re
from datetime import datetime, timedelta

import httpx

from .. import db

GRAPH = "https://graph.microsoft.com/v1.0"
UAE_TIMEZONE = "Arabian Standard Time"   # Windows time zone name Graph uses for UTC+4 (Dubai)


class M365Error(Exception):
    pass


def mode() -> str:
    return "graph" if os.environ.get("HUB_M365", "demo").lower() == "graph" else "demo"


def get_client(conn):
    return GraphM365() if mode() == "graph" else DemoM365(conn)


class DemoM365:
    """A fictional mailbox and calendar. Replies and recaps are scripted and say they are demos."""
    name = "demo"
    label = "Demo mailbox (fictional)"

    def __init__(self, conn):
        self.conn = conn

    def send_mail(self, to: str, subject: str, body: str, reply_to_id: str | None = None) -> dict:
        thread = reply_to_id or f"demo-thread-{db.now()}-{to}"
        message_id = self._store("sent", thread, "me", to, subject, body)
        return {"message_id": message_id, "conversation_id": thread, "sent_at": db.now()}

    def replies(self, conversation_id: str, to: str) -> list[dict]:
        """The supplier 'answers' the first email in a thread once, with two times next week."""
        existing = self._thread(conversation_id, "received")
        if not existing and self._thread(conversation_id, "sent"):
            first = self._thread(conversation_id, "sent")[0]
            monday = datetime.now() + timedelta(days=(7 - datetime.now().weekday()))
            slots = [(monday + timedelta(days=1)).replace(hour=10, minute=0), (monday + timedelta(days=2)).replace(hour=14, minute=0)]
            body = (f"[DEMO REPLY, fictional]\n\nHello,\n\nThank you for reaching out. We'd be glad to set up a call. "
                    f"Would {slots[0]:%A %d %B at %H:%M} or {slots[1]:%A %d %B at %H:%M} (UAE time) work for you?\n\n"
                    "Best regards,\nPartnerships team")
            self._store("received", conversation_id, to, "me", f"RE: {first['subject']}", body)
            existing = self._thread(conversation_id, "received")
        return [{"message_id": str(m["pk"]), "from": m["sender"], "subject": m["subject"], "body": m["body"],
                 "received_at": m["created_at"]} for m in existing]

    def create_meeting(self, subject: str, start: datetime, minutes: int, attendees: list[str], body: str) -> dict:
        event_id = self._store("event", f"demo-event-{db.now()}", "me", ",".join(attendees), subject, body)
        return {"event_id": event_id, "teams_link": f"https://teams.microsoft.com/l/meetup-join/DEMO-{event_id}",
                "web_link": None}

    def transcript(self, teams_link: str, supplier: str) -> str | None:
        return (f"[DEMO TRANSCRIPT, fictional] Meeting with {supplier}. Attendees: Innovation team (Sara), {supplier} "
                "partnerships lead. The supplier showed a demo with sample spreadsheets. They said data can be hosted "
                "in a UAE data center and quoted a setup fee to be confirmed in writing. Sara will send three sample "
                "reports by Thursday. The supplier will send the security certificates and a written quote next week. "
                "Both agreed a two-week pilot at one site is the next step if the quote is acceptable.")

    def _store(self, kind, thread, sender, recipient, subject, body) -> str:
        cursor = self.conn.execute("INSERT INTO m365_demo_items (kind, thread, sender, recipient, subject, body, created_at)"
                                   " VALUES (?, ?, ?, ?, ?, ?, ?)", (kind, thread, sender, recipient, subject, body, db.now()))
        return str(cursor.lastrowid)

    def _thread(self, thread, kind):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM m365_demo_items WHERE thread = ? AND kind = ? ORDER BY pk", (thread, kind))]


class GraphM365:
    """Microsoft Graph v1.0, delegated: everything happens as the signed-in employee, from their own mailbox.

    Permissions to request: Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, OnlineMeetings.Read,
    OnlineMeetingTranscript.Read.All. The access token comes from the sign-in flow (HUB_GRAPH_TOKEN for testing).
    """
    name = "graph"
    label = "Microsoft 365 (Outlook and Teams)"

    def __init__(self, token: str | None = None, transport: httpx.BaseTransport | None = None):
        token = token or os.environ.get("HUB_GRAPH_TOKEN")
        if not token:
            raise M365Error("Not signed in to Microsoft 365")
        self.http = httpx.Client(base_url=GRAPH, headers={"Authorization": f"Bearer {token}"}, timeout=30,
                                 transport=transport)

    def _call(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise M365Error(f"Microsoft Graph {method} {path.split('?')[0]} failed ({response.status_code})")
        return response

    def send_mail(self, to: str, subject: str, body: str, reply_to_id: str | None = None) -> dict:
        # Create a draft first so we know its id and thread (sendMail alone returns nothing), then send it.
        draft = self._call("POST", "/me/messages", json={
            "subject": subject, "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}]}).json()
        self._call("POST", f"/me/messages/{draft['id']}/send")
        return {"message_id": draft["id"], "conversation_id": draft["conversationId"], "sent_at": db.now()}

    def replies(self, conversation_id: str, to: str) -> list[dict]:
        found = self._call("GET", "/me/messages", params={
            "$filter": f"conversationId eq '{conversation_id}'",
            "$select": "id,from,subject,bodyPreview,receivedDateTime"}).json()["value"]
        return [{"message_id": m["id"], "from": m["from"]["emailAddress"]["address"], "subject": m["subject"],
                 "body": m["bodyPreview"], "received_at": m["receivedDateTime"]}
                for m in found if m["from"]["emailAddress"]["address"].lower() == to.lower()]

    def create_meeting(self, subject: str, start: datetime, minutes: int, attendees: list[str], body: str) -> dict:
        end = start + timedelta(minutes=minutes)
        event = self._call("POST", "/me/events", json={
            "subject": subject, "body": {"contentType": "Text", "content": body},
            "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": UAE_TIMEZONE},
            "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": UAE_TIMEZONE},
            "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in attendees],
            "isOnlineMeeting": True, "onlineMeetingProvider": "teamsForBusiness"}).json()
        return {"event_id": event["id"], "teams_link": (event.get("onlineMeeting") or {}).get("joinUrl"),
                "web_link": event.get("webLink")}

    def transcript(self, teams_link: str, supplier: str) -> str | None:
        meetings = self._call("GET", "/me/onlineMeetings",
                              params={"$filter": f"JoinWebUrl eq '{teams_link}'"}).json()["value"]
        if not meetings:
            return None
        transcripts = self._call("GET", f"/me/onlineMeetings/{meetings[0]['id']}/transcripts").json()["value"]
        if not transcripts:
            return None
        vtt = self._call("GET", f"/me/onlineMeetings/{meetings[0]['id']}/transcripts/{transcripts[-1]['id']}/content",
                         params={"$format": "text/vtt"}).text
        return vtt_to_text(vtt)


def vtt_to_text(vtt: str) -> str:
    """Keep the spoken lines ('<v Sara>Hello</v>' → 'Sara: Hello'), drop timings and headers."""
    lines = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        match = re.match(r"<v ([^>]+)>(.*?)(</v>)?$", line)
        lines.append(f"{match.group(1)}: {match.group(2)}" if match else line)
    return "\n".join(lines)
