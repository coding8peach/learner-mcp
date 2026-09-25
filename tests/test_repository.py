"""End-to-end against a real (throwaway!) Postgres with scripts/schema.sql.

Runs only when TEST_DATABASE_URL is set, so it can never touch your real
data by accident. GitHub Actions sets it to a fresh database per run.
Locally, point it at a scratch database:

    TEST_DATABASE_URL=postgresql://... uv run pytest
"""
import os
import uuid

import pytest

TEST_DB = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DB, reason="set TEST_DATABASE_URL to run database tests")

ABCD = [{"label": x, "content": x.lower()} for x in "ABCD"]


@pytest.fixture(scope="module")
def repo():
    os.environ["DATABASE_URL"] = TEST_DB     # the pool reads this on first use
    from learner_mcp import repository
    return repository


@pytest.fixture
def student():
    return f"student-{uuid.uuid4().hex[:8]}"  # isolates each test's data


def make_test(repo, items, title="Quiz", status="ready"):
    from learner_mcp.models import SectionIn
    return repo.create_test_set(title=title, subject="test", source="manual", status=status,
                                sections=[SectionIn(title="Part 1", time_limit_seconds=600, items=items)])


def mixed_items():
    return [
        {"stem": "Pick B", "choices": ABCD, "answer": "B", "domain_code": "D1", "domain": "Reading",
         "topic_code": "INF", "topic": "Inferences"},
        {"stem": "Pick A and C", "kind": "multi_choice", "choices": ABCD, "answers": ["A", "C"], "points": 2,
         "domain_code": "D2", "domain": "Math", "topic_code": "NUM", "topic": "Numbers"},
        {"stem": "4x = 3", "kind": "numeric", "answers": ["3/4"], "domain_code": "D2", "domain": "Math",
         "topic_code": "LIN", "topic": "Linear"},
        {"stem": "Explain.", "kind": "free_response", "points": 5, "domain_code": "D1", "domain": "Reading",
         "topic_code": "INF", "topic": "Inferences"},
    ]


def test_answers_hidden_until_submitted(repo, student):
    made = make_test(repo, mixed_items())
    assert made.question_count == 4
    hidden = repo.get_test_set(made.id)
    assert all(i.answers is None and i.explanation is None for i in hidden.sections[0].items)
    shown = repo.get_test_set(made.id, include_answers=True)
    assert shown.sections[0].items[0].answers == ["B"]

    started = repo.start_test_session(made.id, student)
    assert all(i.answers is None for i in started.test.sections[0].items)


def test_submit_grades_every_kind(repo, student):
    made = make_test(repo, mixed_items())
    started = repo.start_test_session(made.id, student)
    ids = [str(i.id) for i in started.test.sections[0].items]
    res = repo.submit_test_session(
        started.session_id,
        {ids[0]: "b", ids[1]: ["C", "A"], ids[2]: "0.75", ids[3]: "Plants use light."},
        flagged=[ids[2]],
    )
    assert (res.correct, res.graded, res.total, res.needs_review) == (3, 3, 4, 1)
    assert (res.points_earned, res.points_possible) == (4.0, 4.0)
    assert [i.reasoning for i in res.items] == ["strong", "strong", "shaky", None]
    assert {d.name: d.points_earned for d in res.domains} == {"Math": 3.0, "Reading": 1.0}


def test_submit_rules(repo, student):
    made = make_test(repo, mixed_items()[:1])
    started = repo.start_test_session(made.id, student)
    with pytest.raises(ValueError, match="not in this test"):
        repo.submit_test_session(started.session_id, {"not-a-real-id": "A"})
    item_id = str(started.test.sections[0].items[0].id)
    res = repo.submit_test_session(started.session_id, {item_id: "C"})   # still open after the bad try
    assert res.correct == 0 and res.items[0].reasoning == "missed"
    with pytest.raises(ValueError, match="already submitted"):
        repo.submit_test_session(started.session_id, {item_id: "B"})


def test_drafts_cannot_be_taken(repo, student):
    made = make_test(repo, mixed_items()[:1], status="draft")
    with pytest.raises(ValueError, match="not ready"):
        repo.start_test_session(made.id, student)
    repo.set_test_set_status(made.id, "ready")
    assert repo.start_test_session(made.id, student).session_id


def test_progress_and_focus(repo, student):
    from learner_mcp.models import AttemptIn
    for ok, reasoning in [(True, "strong"), (False, "missed"), (True, "shaky"), (False, "missed")]:
        repo.record_attempt(AttemptIn(student=student, subject="test", topic_code="INF", topic="Inferences",
                                      domain_code="D1", domain="Reading", correct_final=ok,
                                      reasoning=reasoning, seconds=30), app="pytest")
    repo.record_attempt(AttemptIn(student=student, subject="test", topic_code="TRA", topic="Transitions",
                                  correct_final=True, reasoning="strong"))

    p = repo.get_progress(student, "test")
    assert (p.total, p.strong, p.shaky, p.missed) == (5, 2, 1, 2)
    inf = next(g for g in p.groups if g.code == "INF")
    assert (inf.done, inf.accuracy, inf.practice_accuracy, inf.timed_accuracy) == (4, 0.5, 0.5, None)
    assert [g.code for g in p.focus_next] == ["INF"]       # Transitions: too few tries to judge
    assert [g.code for g in repo.get_progress(student, "test", group_by="domain").groups] == ["D1", None]

    history = repo.list_attempts(student, limit=2)
    assert len(history) == 2 and history[0].topic_code == "TRA"


def test_new_student_has_empty_progress(repo):
    p = repo.get_progress("nobody-" + uuid.uuid4().hex)
    assert (p.total, p.groups, p.focus_next) == (0, [], [])


def test_unknown_ids(repo):
    with pytest.raises(ValueError, match="not found"):
        repo.get_test_set(uuid.uuid4())
    with pytest.raises(ValueError, match="valid"):
        repo.get_test_set("nope")
