"""Grading for every question kind (no database needed)."""
import pytest

from learner_mcp.grading import grade, labels, number, response_text


@pytest.mark.parametrize(
    "kind, answers, response, kwargs, expected",
    [
        # single choice
        ("single_choice", ["B"], "b", {}, (True, 1.0)),
        ("single_choice", ["B"], "C", {}, (False, 0.0)),
        ("single_choice", ["B"], None, {}, (False, 0.0)),
        # select all that apply
        ("multi_choice", ["A", "C"], "c, a", {}, (True, 1.0)),
        ("multi_choice", ["A", "C"], ["C", "A"], {}, (True, 1.0)),
        ("multi_choice", ["A", "C"], "A", {}, (False, 0.0)),
        ("multi_choice", ["A", "C"], "ABC", {}, (False, 0.0)),
        ("multi_choice", ["A", "C"], ["A", "B"], {"points": 2, "partial_credit": True}, (False, 0.0)),
        ("multi_choice", ["A", "B", "C"], "AB", {"points": 3, "partial_credit": True}, (False, 2.0)),
        # typed numbers
        ("numeric", ["3/4"], ".75", {}, (True, 1.0)),
        ("numeric", ["0.75"], "3/4", {}, (True, 1.0)),
        ("numeric", ["2.5", "5/2"], "5/2", {}, (True, 1.0)),
        ("numeric", ["1000"], "1,000", {}, (True, 1.0)),
        ("numeric", ["3.14"], "3.1416", {"tolerance": 0.01}, (True, 1.0)),
        ("numeric", ["3.14"], "3.1416", {}, (False, 0.0)),
        ("numeric", ["7"], "8", {}, (False, 0.0)),
        ("numeric", ["7"], "seven", {}, (False, 0.0)),
        ("numeric", ["7"], "1/0", {}, (False, 0.0)),
        # short text
        ("short_text", ["mitochondria"], " Mitochondria. ", {}, (True, 1.0)),
        ("short_text", ["mitochondria", "mitochondrion"], "mitochondrion", {}, (True, 1.0)),
        ("short_text", ["mitochondria"], "nucleus", {}, (False, 0.0)),
        ("short_text", ["mitochondria"], "", {}, (False, 0.0)),
        # not auto-graded
        ("free_response", [], "an essay", {}, (None, None)),
        ("single_choice", [], "A", {}, (None, None)),
    ],
)
def test_grade(kind, answers, response, kwargs, expected):
    assert grade(kind, answers, response, **kwargs) == expected


def test_points_scale():
    assert grade("single_choice", ["A"], "A", points=5) == (True, 5.0)


def test_unknown_kind():
    with pytest.raises(ValueError):
        grade("essay", ["x"], "x")


@pytest.mark.parametrize("response, expected", [
    ("a, c", ["A", "C"]), (["c", "a"], ["A", "C"]), ("AC", ["A", "C"]), ("b", ["B"]), (None, []), ("", []),
])
def test_labels(response, expected):
    assert labels(response) == expected


@pytest.mark.parametrize("value, expected", [
    ("3/4", 0.75), (".75", 0.75), ("-2", -2.0), (" 1,000 ", 1000.0), ("abc", None), ("1/0", None), (None, None),
])
def test_number(value, expected):
    assert number(value) == expected


def test_response_text():
    assert response_text("multi_choice", ["c", "a"]) == "A,C"
    assert response_text("numeric", " 0.75 ") == "0.75"
    assert response_text("single_choice", "") is None
