"""The shapes of data the app accepts and returns, and the shared vocabulary:
departments, statuses, routes and innovation tracks."""
from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator

Department = Literal["Not specified", "Operations", "Engineering", "Facilities", "Finance", "Human resources",
                     "IT", "Procurement", "Security", "Other"]
DEPARTMENTS = list(get_args(Department))

Status = Literal["Submitted", "Routed", "Linked", "Needs clarification", "Under review",
                 "Accepted", "Declined", "Resolved", "Research", "Pilot planning",
                 "Pilot running", "Scaling", "Rolling out", "In operation", "Stopped"]
OPEN_STATUSES = {"Submitted", "Routed", "Needs clarification", "Under review"}

# Where a request goes first. Urgency and innovation potential are separate decisions:
# every request gets a route, and separately an innovation track.
# These are PROPOSED routes, to be validated with the real department owners.
Route = Literal["incident", "it_support", "hr", "facilities_procurement",
                "process_owner_innovation", "innovation_screening", "human_triage"]
ROUTES = {
    "incident": "Operations, safety or security incident channel",
    "it_support": "IT support",
    "hr": "HR",
    "facilities_procurement": "Facilities, maintenance or procurement",
    "process_owner_innovation": "Process owner + innovation screening",
    "innovation_screening": "Innovation screening",
    "human_triage": "Human triage",
}
ROUTINE_ROUTES = {"it_support", "hr", "facilities_procurement"}
INNOVATION_ROUTES = {"process_owner_innovation", "innovation_screening"}

# none = no innovation involvement; screening = the agent found innovation potential;
# employee_requested = the employee asked for a review, which guarantees a human decision.
InnovationTrack = Literal["none", "screening", "employee_requested"]

Feasibility = Literal["ready_to_investigate", "needs_discovery", "blocked"]

# Single-user demo: every new submission belongs to this fictional employee.
# This is NOT authentication. Real sign-in comes in a later milestone.
DEMO_USER = "demo-employee"


# A new submission. FastAPI rejects anything that doesn't fit (422 error).
class SubmissionIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    department: Department = "Not specified"
    current_process: str | None = Field(default=None, max_length=1000)   # today, and what should happen instead
    people_affected: str | None = Field(default=None, max_length=300)    # who, or which locations
    frequency: str | None = Field(default=None, max_length=300)
    impact: str | None = Field(default=None, max_length=1000)            # time, cost, delay or risk
    tried_already: str | None = Field(default=None, max_length=1000)
    desired_outcome: str | None = Field(default=None, max_length=1000)
    suggested_solution: str | None = Field(default=None, max_length=1000)

    # "   " is not a title: strip spaces so min_length catches it.
    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_required(cls, value):
        return value.strip() if isinstance(value, str) else value

    # An empty optional answer is stored as NULL, which means "unknown".
    @field_validator("current_process", "people_affected", "frequency", "impact", "tried_already",
                     "desired_outcome", "suggested_solution", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
        return value or None


# A submission the server sends back.
class SubmissionOut(SubmissionIn):
    id: str
    submitted_by: str
    created_at: str
    status: Status
    review_question: str | None
    route: Route | None = None
    route_reason: str | None = None
    initial_route: Route | None = None
    innovation_track: InnovationTrack = "none"
    linked_to: str | None = None          # the shared opportunity this request was linked to
    feasibility: Feasibility | None = None
    brief: dict | None = None             # the PROPOSED brief, including the priority rubric
    score: float | None = None            # priority 0–100 (unknown criteria excluded, not zero)
    supporters: int = 0                   # other employees' requests linked to this one
    recommendation: dict | None = None    # screening's PROPOSED next decision
    decision_reason: str | None = None
    decision_message: str | None = None
    decided_by: str | None = None
    review_outcome: str | None = None
    appealed: bool = False
    resolution_confirmed: bool = False
    solutions: dict | None = None         # Research AI's ranked solution options (PROPOSED)
    research: dict | None = None          # the selected option and research plan
