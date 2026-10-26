"""The shared message board: what the bots say to each other, and the rules on the table."""
from dataclasses import dataclass, field

from .rules import Rule


@dataclass
class Message:
    phase: str          # opening, proposal, results, review, reply, withdrawal, vote, verdict
    round: int
    author: str
    text: str
    to: str = ""        # the bot addressed, if any
    candidate: str = ""
    brain: str = "scripted"

    def to_dict(self) -> dict:
        return {key: value for key, value in self.__dict__.items() if value != ""}


@dataclass
class Candidate:
    """A rule on the table, owned by the bot that proposed it. Accepted amendments make new versions."""
    id: str
    author: str
    rule: Rule
    version: int = 1
    status: str = "active"  # or "withdrawn"
    history: list = field(default_factory=list)  # (version, rule dict, what changed and who suggested it)

    def amend(self, rule: Rule, note: str):
        self.version += 1
        self.rule = rule
        self.history.append({"version": self.version, "rule": rule.to_dict(), "change": note})


@dataclass
class Review:
    critic: str
    candidate: str
    text: str
    amendment: Rule | None = None
    change: str = ""
    id: str = ""        # set by the council when the amendment is put to the author


@dataclass
class Reply:
    amendment: str      # the Review id it answers
    accept: bool
    text: str


@dataclass
class Board:
    messages: list = field(default_factory=list)
    listeners: list = field(default_factory=list)

    def post(self, message: Message) -> Message:
        self.messages.append(message)
        for listener in self.listeners:
            listener(message)
        return message
