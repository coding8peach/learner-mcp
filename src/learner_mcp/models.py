"""Shapes the learner-mcp tools accept and return.

Nothing here is SAT-specific: a "topic" is whatever the app groups
questions by (an SAT skill, a biology unit, a vocabulary list...).
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

Reasoning = Literal["strong", "shaky", "missed"]
Mode = Literal["practice", "timed"]
Kind = Literal["single_choice", "multi_choice", "numeric", "short_text", "free_response"]
Response = str | list[str]


# ---------------- test sets ----------------

class Choice(BaseModel):
    label: str = Field(description="A, B, C, D...")
    content: str


class ItemIn(BaseModel):
    """A question to put in a test set."""
    stem: str = Field(description="The question itself")
    kind: Kind = Field(default="single_choice", description=(
        "single_choice | multi_choice (select all that apply) | numeric (typed number; "
        "'3/4' and '0.75' match) | short_text | free_response (not auto-graded)"))
    choices: list[Choice] = Field(default_factory=list, description="For single/multi choice")
    answers: list[str] = Field(default_factory=list, description=(
        "Accepted answers: the correct label(s) for choice questions, accepted values or "
        "texts otherwise. Empty = not auto-graded."))
    answer: str | None = Field(default=None, description="Shortcut for a single accepted answer")
    tolerance: float | None = Field(default=None, description="numeric: allowed difference")
    points: float = Field(default=1, ge=0)
    passage: str | None = None
    explanation: str | None = None
    domain_code: str | None = Field(default=None, description="Broader group, e.g. SAT domain or course unit")
    domain: str | None = None
    topic_code: str | None = Field(default=None, description="e.g. SAT skill or lesson")
    topic: str | None = None
    tags: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    item_ref: str | None = Field(default=None, description="Where it came from, e.g. 'sat:61228830'")
    figure_urls: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict, description="Extra data; meta.partial_credit=true for multi_choice")

    @model_validator(mode="after")
    def check_answers(self):
        if self.answer and not self.answers:
            self.answers = [self.answer]
        self.answer = None
        answers = [a.strip() for a in self.answers if str(a).strip()]

        if self.kind in ("single_choice", "multi_choice"):
            if len(self.choices) < 2:
                raise ValueError(f"{self.kind} needs at least 2 choices")
            valid = {c.label.strip().upper() for c in self.choices}
            answers = [a.upper() for a in answers]
            wrong = [a for a in answers if a not in valid]
            if wrong:
                raise ValueError(f"answer {wrong} is not one of the choices {sorted(valid)}")
            if self.kind == "single_choice" and len(answers) > 1:
                raise ValueError("single_choice has one answer; use multi_choice for several")
        elif self.kind == "numeric":
            from learner_mcp.grading import number
            bad = [a for a in answers if number(a) is None]
            if bad:
                raise ValueError(f"numeric answers must be numbers or fractions: {bad}")
        elif self.kind == "free_response":
            answers = []   # graded by a person or tutor, not automatically
        self.answers = answers
        return self


class SectionIn(BaseModel):
    title: str
    time_limit_seconds: int | None = Field(default=None, description="Null = untimed")
    items: list[ItemIn] = Field(min_length=1)


class Item(BaseModel):
    id: UUID
    position: int
    kind: Kind
    stem: str
    choices: list[Choice]
    points: float
    passage: str | None = None
    domain_code: str | None = None
    domain: str | None = None
    topic_code: str | None = None
    topic: str | None = None
    tags: list[str] = []
    difficulty: str | None = None
    item_ref: str | None = None
    figure_urls: list[str] = []
    answers: list[str] | None = Field(default=None, description="Only when answers were requested")
    tolerance: float | None = None
    explanation: str | None = Field(default=None, description="Only when answers were requested")


class Section(BaseModel):
    id: UUID
    position: int
    title: str
    time_limit_seconds: int | None
    items: list[Item]


class TestSetSummary(BaseModel):
    id: UUID
    title: str
    subject: str
    source: str
    status: str
    question_count: int
    total_seconds: int | None
    created_at: datetime


class TestSet(BaseModel):
    id: UUID
    title: str
    subject: str
    source: str
    status: str
    scoring: dict = Field(default_factory=dict, description="Reserved: scaled scores, adaptive routing")
    meta: dict
    sections: list[Section]


class Created(BaseModel):
    id: UUID
    question_count: int = 0


# ---------------- sessions ----------------

class SessionStarted(BaseModel):
    session_id: UUID
    test: TestSet = Field(description="The test without answers")


class ItemResult(BaseModel):
    item_id: UUID
    section: str
    position: int
    kind: Kind
    domain_code: str | None
    domain: str | None
    topic_code: str | None
    topic: str | None
    chosen: str | None = Field(description="The response; choice labels joined like 'A,C'")
    answers: list[str] = Field(description="Accepted answers, revealed after submitting")
    correct: bool | None = Field(description="null when not auto-graded")
    points_earned: float | None
    points_possible: float
    needs_review: bool = Field(description="True for responses a person or tutor must grade")
    flagged: bool
    reasoning: Reasoning | None


class GroupScore(BaseModel):
    code: str | None
    name: str | None
    correct: int
    total: int = Field(description="Auto-graded questions")
    points_earned: float
    points_possible: float


class SessionResult(BaseModel):
    session_id: UUID
    correct: int
    graded: int = Field(description="Questions graded automatically")
    total: int
    needs_review: int
    points_earned: float
    points_possible: float
    sections: list[GroupScore]
    domains: list[GroupScore]
    topics: list[GroupScore]
    items: list[ItemResult]


# ---------------- attempts & progress ----------------

class AttemptIn(BaseModel):
    student: str
    subject: str = "general"
    item_ref: str | None = None
    kind: Kind | None = None
    domain_code: str | None = None
    domain: str | None = None
    topic_code: str | None = None
    topic: str | None = None
    difficulty: str | None = None
    mode: Mode = "practice"
    first_answer: str | None = None
    final_answer: str | None = None
    correct_first: bool | None = None
    correct_final: bool | None = None
    reasoning: Reasoning | None = None
    needs_review: bool = False
    points_earned: float | None = None
    points_possible: float | None = None
    coaching_rounds: int | None = None
    found_evidence: bool | None = None
    flagged: bool | None = None
    seconds: float | None = None
    meta: dict = Field(default_factory=dict)

    @field_validator("student")
    @classmethod
    def student_named(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("student is required")
        return v


class Attempt(AttemptIn):
    id: UUID
    created_at: datetime
    app: str | None = None


class GroupStats(BaseModel):
    code: str | None = Field(description="topic_code or domain_code, depending on group_by")
    name: str | None
    done: int
    strong: int
    shaky: int
    missed: int
    accuracy: float = Field(description="Share with a correct final answer, 0-1 (auto-graded only)")
    practice_accuracy: float | None
    timed_accuracy: float | None
    avg_seconds: float | None


class Progress(BaseModel):
    student: str
    subject: str | None
    days: int
    group_by: Literal["topic", "domain"]
    total: int
    strong: int
    shaky: int
    missed: int
    needs_review: int
    groups: list[GroupStats]
    focus_next: list[GroupStats] = Field(description="Groups most worth practicing next")
