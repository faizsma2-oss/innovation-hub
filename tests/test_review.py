"""Screening, prioritisation and review: does each request get the right route, priority and
recommendation, and do the reviewer and employee actions follow the rules?"""
import pytest


def submit(client, description, title=None, **fields):
    body = {"title": title or description[:60], "description": description, "department": "Operations"} | fields
    response = client.post("/api/submissions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def strong(client):
    return submit(client, "Every week we manually combine energy reports from several systems.",
                  current_process="Copy numbers from 3 tools into a spreadsheet; should be automatic.",
                  people_affected="The reporting team at 4 sites", impact="About 6 hours a week")


def low_value(client):
    return submit(client, "Every month someone re-types the kettle cleaning rota.",
                  frequency="rarely", people_affected="2 people", impact="minor annoyance")


def review(client, record, **body):
    return client.post(f"/api/submissions/{record['id']}/review", json=body)


# ── Routing before ranking ───────────────────────────────────────────────────

def test_samples_are_routed_and_screened_at_startup(client):
    sample = client.get("/api/submissions/SUB-0001").json()
    assert sample["route"] == "process_owner_innovation"
    assert sample["recommendation"] is not None


@pytest.mark.parametrize("description, route", [
    ("I cannot access the reporting system.", "it_support"),
    ("My payslip for September is missing.", "hr"),
    ("A sensor is faulty in Hall C and needs replacing.", "facilities_procurement"),
    ("Every week, we manually combine reports from several systems.", "process_owner_innovation"),
    ("I saw an interesting inspection robot at a trade show.", "innovation_screening"),
    ("Something about the onboarding feels off to several of us.", "human_triage"),
])
def test_requests_are_routed_to_the_right_first_owner(client, description, route):
    assert submit(client, description)["route"] == route


def test_routine_request_is_routed_with_no_innovation_action(client):
    record = submit(client, "I cannot access the reporting system.")
    assert record["status"] == "Routed"
    assert record["recommendation"]["decision"] == "route"


def test_unclear_request_goes_to_human_triage(client):
    record = submit(client, "Something about the onboarding feels off to several of us.")
    assert record["recommendation"]["decision"] in ("triage", "ask")


# ── Transparent prioritisation ───────────────────────────────────────────────

def test_rubric_weights_and_unknown_is_not_zero(client):
    record = submit(client, "Every week we manually re-enter shift data.", impact="About 6 hours a week")
    priority = record["brief"]["priority"]
    assert {c["weight"] for c in priority["criteria"].values()} == {0.35, 0.25, 0.2}
    known = {name: c for name, c in priority["criteria"].items() if c["value"] is not None}
    unknown = [c["name"] for c in priority["criteria"].values() if c["value"] is None]
    assert priority["unknown"] == unknown
    expected = round(sum(c["weight"] * c["value"] for c in known.values())
                     / sum(c["weight"] for c in known.values()) * 20)
    assert priority["score"] == expected  # unknown criteria left out, not counted as zero


def test_strong_opportunity_is_recommended_for_acceptance(client):
    record = strong(client)
    assert record["recommendation"]["decision"] == "accept"
    assert record["brief"]["priority"]["confidence"] == "high"
    assert record["feasibility"] == "ready_to_investigate"
    assert "Vendor research only after" in record["brief"]["next_step"]


def test_little_information_means_ask_not_decline(client):
    record = submit(client, "Our team feels shift handovers could be smoother overall.", title="Handovers")
    assert record["recommendation"]["decision"] in ("ask", "triage")


def test_low_value_is_recommended_for_decline_but_not_applied(client):
    record = low_value(client)
    assert record["recommendation"]["decision"] == "decline"
    assert record["recommendation"]["reason_code"] == "low_value"
    assert record["status"] == "Submitted"


def test_blocked_feasibility_is_a_separate_label(client):
    record = submit(client, "Every week we manually rebuild the capacity forecast but we are waiting for access "
                            "to data from the vendor.", impact="2 days a month")
    assert record["feasibility"] == "blocked"


# ── Policy declines ──────────────────────────────────────────────────────────

def test_weakening_a_control_is_declined_automatically(client):
    record = submit(client, "Can we disable the badge checks at the loading dock gate to speed up deliveries?")
    assert record["status"] == "Declined" and record["decided_by"] == "screening-policy"


def test_employee_requested_review_is_never_auto_declined(chat):
    c = chat()
    c.say("Can we disable the badge checks at the loading dock gate to speed up deliveries?")
    c.click("request_review")
    reply = c.click("submit")
    assert reply["outcome"] != "auto_declined"
    submission = c.submission()
    assert submission["status"] == "Submitted"
    assert submission["recommendation"]["decision"] == "decline"
    assert submission["recommendation"]["auto_applied"] is False


def test_not_a_request_is_declined_automatically(client):
    assert submit(client, "test", title="test")["status"] == "Declined"


# ── Linking related requests ─────────────────────────────────────────────────

def test_similar_request_is_recommended_for_linking(client):
    record = submit(client, "Several sites repeat inspection paperwork: handwritten inspection notes are copied "
                            "into shared reports by hand.")
    assert record["recommendation"]["decision"] == "link"
    assert record["recommendation"]["link_to"] == "SUB-0001"


def test_reviewer_links_requests_keeping_both_records(client):
    record = submit(client, "Several sites repeat inspection paperwork: handwritten inspection notes are copied "
                            "into shared reports by hand.")
    linked = review(client, record, decision="link", link_to="SUB-0001").json()
    assert linked["status"] == "Linked" and linked["linked_to"] == "SUB-0001"
    assert linked["review_outcome"] == "agreed"
    assert client.get("/api/submissions/SUB-0001").json()["supporters"] == 1
    assert review(client, strong(client), decision="link", link_to="SUB-9999").status_code == 422


# ── Reviewer corrections ─────────────────────────────────────────────────────

def test_reroute_is_logged_and_lowers_routing_accuracy(client):
    record = submit(client, "I cannot access the reporting system.")
    rerouted = client.post(f"/api/submissions/{record['id']}/reroute",
                           json={"route": "process_owner_innovation", "reason": "Access is fine; reports are the issue"})
    data = rerouted.json()
    assert data["route"] == "process_owner_innovation" and data["innovation_track"] == "screening"
    assert data["status"] == "Submitted"
    metrics = client.get("/api/metrics").json()
    assert metrics["routing_accuracy"] == 0.0 and metrics["routing_corrections"] == 1


def test_score_correction_recalculates_and_survives_rescreening(client):
    record = strong(client)
    corrected = client.post(f"/api/submissions/{record['id']}/scores",
                            json={"criterion": "alignment", "value": 1, "reason": "Not a current priority"}).json()
    criterion = corrected["brief"]["priority"]["criteria"]["alignment"]
    assert criterion["value"] == 1 and criterion["corrected_by"] == "demo-reviewer"
    assert corrected["score"] < record["score"]
    rerouted = client.post(f"/api/submissions/{record['id']}/reroute",
                           json={"route": "innovation_screening", "reason": "Needs a new tool"}).json()
    assert rerouted["brief"]["priority"]["criteria"]["alignment"]["value"] == 1


def test_feasibility_can_be_set_by_reviewer(client):
    record = strong(client)
    updated = client.post(f"/api/submissions/{record['id']}/feasibility", json={"label": "blocked"}).json()
    assert updated["feasibility"] == "blocked"
    assert "blocker" in updated["brief"]["next_step"]


# ── Employee override and confirmed resolutions ──────────────────────────────

def test_employee_can_request_review_of_a_routed_request(client):
    record = submit(client, "I cannot access the reporting system.")
    requested = client.post(f"/api/submissions/{record['id']}/request-review", json={"text": "It happens weekly"}).json()
    assert requested["innovation_track"] == "employee_requested"
    assert requested["status"] == "Routed"  # still routed for today's help
    assert client.get("/api/metrics").json()["employee_requested_open"] == 1
    assert client.post(f"/api/submissions/{record['id']}/request-review", json={}).status_code == 409


def test_missed_opportunity_is_measured(client):
    record = submit(client, "I cannot access the reporting system.")
    client.post(f"/api/submissions/{record['id']}/request-review", json={})
    review(client, record, decision="accept")
    assert client.get("/api/metrics").json()["missed_opportunities"] == 1


def test_employee_confirms_a_routed_request_is_resolved(client):
    record = submit(client, "I cannot access the reporting system.")
    resolved = client.post(f"/api/submissions/{record['id']}/resolve").json()
    assert resolved["status"] == "Resolved" and resolved["resolution_confirmed"] is True
    assert client.get("/api/metrics").json()["confirmed_resolutions"] == 1
    assert client.post(f"/api/submissions/{record['id']}/resolve").status_code == 409


# ── Reviewer decisions ───────────────────────────────────────────────────────

def test_decline_needs_a_reason_and_a_message(client):
    record = low_value(client)
    assert review(client, record, decision="decline", message="No").status_code == 422
    assert review(client, record, decision="decline", reason_code="low_value").status_code == 422
    assert review(client, record, decision="ask").status_code == 422


def test_agreement_and_reviewer_time_are_recorded(client):
    agreed = review(client, low_value(client), decision="decline", reason_code="low_value", message="Not now.",
                    review_seconds=40).json()
    assert agreed["review_outcome"] == "agreed"
    overrode = review(client, low_value(client), decision="accept", review_seconds=80).json()
    assert overrode["review_outcome"] == "overrode"
    metrics = client.get("/api/metrics").json()
    assert metrics["agreement_rate"] == 0.5
    assert metrics["reviewer_time_seconds"] == 60


def test_final_decisions_cannot_be_changed(client):
    record = review(client, strong(client), decision="accept").json()
    assert review(client, record, decision="decline", reason_code="other", message="Changed mind").status_code == 409


def test_ask_reply_and_history(client):
    record = strong(client)
    assert review(client, record, decision="ask", message="Which halls?").json()["status"] == "Needs clarification"
    assert client.post(f"/api/submissions/{record['id']}/reply", json={"text": "A and B"}).json()["status"] == "Under review"
    events = [event["event"] for event in client.get(f"/api/submissions/{record['id']}/history").json()]
    assert events == ["submitted", "screened", "asked", "replied"]


def test_auto_decline_can_be_appealed_once_and_overturned(client):
    record = submit(client, "Can we disable the badge checks at the loading dock gate to speed up deliveries?")
    client.post(f"/api/submissions/{record['id']}/appeal", json={"text": "We mean faster scanners."})
    assert client.post(f"/api/submissions/{record['id']}/appeal", json={"text": "again"}).status_code == 409
    assert review(client, record, decision="accept").json()["review_outcome"] == "overturned_auto"
    assert client.get("/api/metrics").json()["auto_declines_overturned"] == 1


def test_criteria_are_listed_for_the_reviewer(client):
    codes = [criterion["code"] for criterion in client.get("/api/review/criteria").json()]
    assert codes == ["not_a_request", "policy", "duplicate", "out_of_scope", "low_value", "other"]
