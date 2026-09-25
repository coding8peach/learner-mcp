"""Question validation: bad questions are refused with clear messages."""
import pytest
from pydantic import ValidationError

from learner_mcp.models import AttemptIn, ItemIn

ABCD = [{"label": x, "content": x.lower()} for x in "ABCD"]


def test_answer_shortcut_becomes_answers():
    item = ItemIn(stem="q", choices=ABCD, answer="b")
    assert item.answers == ["B"] and item.answer is None


def test_single_choice_needs_one_answer():
    with pytest.raises(ValidationError, match="single_choice has one answer"):
        ItemIn(stem="q", choices=ABCD, answers=["A", "B"])


def test_answer_must_be_a_choice():
    with pytest.raises(ValidationError, match="not one of the choices"):
        ItemIn(stem="q", choices=ABCD, answer="E")


def test_choice_questions_need_choices():
    with pytest.raises(ValidationError, match="at least 2 choices"):
        ItemIn(stem="q", kind="multi_choice", answers=["A"])


def test_numeric_answers_must_be_numbers():
    with pytest.raises(ValidationError, match="numbers or fractions"):
        ItemIn(stem="q", kind="numeric", answers=["seven"])
    assert ItemIn(stem="q", kind="numeric", answers=["3/4", "0.75"]).answers == ["3/4", "0.75"]


def test_free_response_is_never_auto_graded():
    assert ItemIn(stem="Explain.", kind="free_response", answers=["anything"]).answers == []


def test_points_cannot_be_negative():
    with pytest.raises(ValidationError):
        ItemIn(stem="q", choices=ABCD, answer="A", points=-1)


def test_attempt_needs_a_student():
    with pytest.raises(ValidationError, match="student is required"):
        AttemptIn(student="   ")
