"""The intake API: the routes the chat window talks to."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from . import workflow

router = APIRouter(prefix="/api/intake", tags=["intake"])


class MessageIn(BaseModel):
    text: str | None = Field(default=None, max_length=2000)    # something the employee typed
    action: str | None = Field(default=None, max_length=100)   # or a button they clicked
    edits: dict[str, str | None] = Field(default_factory=dict) # changes made in the summary panel

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.text is None) == (self.action is None):
            raise ValueError("Send either text or an action")
        return self


class Option(BaseModel):
    label: str
    action: str


class IntakeReply(BaseModel):
    session_id: str
    stage: str
    message: str
    options: list[Option]
    draft: dict[str, str | None]
    unknown: list[str]
    outcome: str | None
    submission_id: str | None
    can_submit: bool                 # "Submit now" is available
    review_requested: bool           # the employee asked for an innovation review


class RatingIn(BaseModel):
    score: int = Field(ge=1, le=5)   # 1 = very hard, 5 = very easy


@router.post("/sessions", response_model=IntakeReply, status_code=201)
def start_conversation():
    return workflow.start_session()


@router.post("/sessions/{session_id}/messages", response_model=IntakeReply)
def send_message(session_id: str, message: MessageIn):
    try:
        return workflow.handle_message(session_id, message.text, message.action, message.edits)
    except workflow.IntakeError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("/sessions/{session_id}/rating", status_code=204)
def rate_conversation(session_id: str, rating: RatingIn):
    try:
        workflow.rate(session_id, rating.score)
    except workflow.IntakeError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


@router.get("/stats")
def intake_stats():
    return workflow.stats()
