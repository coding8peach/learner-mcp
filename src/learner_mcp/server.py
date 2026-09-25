"""learner-mcp: an MCP server for timed tests and learning progress.

Works for any subject. Apps (Sidekick, AdaptiveSAT, ...) use it to:
  - save test sets (from a question bank, an uploaded PDF, or by hand)
  - run timed sittings, graded here so answers never reach the student early
  - record every practice attempt
  - read a student's progress by topic, with what to focus on next
"""
import logging
from contextlib import contextmanager

import psycopg
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from learner_mcp import repository as repo
from learner_mcp.models import (
    Attempt,
    AttemptIn,
    Created,
    Progress,
    SectionIn,
    SessionResult,
    SessionStarted,
    TestSet,
    TestSetSummary,
)

mcp = MCPServer("Learner")
logger = logging.getLogger("learner_mcp")


@contextmanager
def expected_errors():
    """Show fixable problems (unknown test, bad input, database down) to
    the calling app instead of the SDK's bare "Error executing tool"."""
    try:
        yield
    except ValueError as e:
        raise ToolError(str(e)) from e
    except (RuntimeError, psycopg.Error) as e:
        logger.exception("Database error")
        raise ToolError(f"Database error: {type(e).__name__}: {e}") from e


# ---------------- test sets ----------------

@mcp.tool()
def create_test_set(
    title: str,
    sections: list[SectionIn],
    subject: str = "general",
    source: str = "manual",
    status: str = "ready",
    scoring: dict | None = None,
    meta: dict | None = None,
    app: str | None = None,
) -> Created:
    """
    Save a test: one or more sections, each with an optional time limit
    and a list of questions.

    Question kinds: single_choice, multi_choice (select all that apply),
    numeric (typed number; "3/4" and "0.75" both match), short_text, and
    free_response (not auto-graded). Each question has points (default 1),
    an optional domain > topic grouping, and tags.

    Args:
        title: e.g. "SAT R&W practice, Module 1"
        sections: [{title, time_limit_seconds, items: [...]}]
        subject: grouping for tests and progress, e.g. "sat-rw", "biology"
        source: "bank", "upload" or "manual"
        status: "ready", or "draft" while it still needs review
        scoring: reserved for scaled scores / adaptive routing (store only)
        app: the calling app, for your records
    """
    with expected_errors():
        return repo.create_test_set(title=title, subject=subject, source=source, sections=sections,
                                    status=status, scoring=scoring, meta=meta, created_by=app)


@mcp.tool()
def list_test_sets(subject: str | None = None, status: str | None = "ready") -> list[TestSetSummary]:
    """List saved tests (newest first). status=None lists every status."""
    with expected_errors():
        return repo.list_test_sets(subject, status)


@mcp.tool()
def get_test_set(set_id: str, include_answers: bool = False) -> TestSet:
    """
    Get a test with all its sections and questions.

    Answers and explanations are left out unless include_answers is True
    (for review screens, never for a student taking the test).
    """
    with expected_errors():
        return repo.get_test_set(set_id, include_answers)


@mcp.tool()
def set_test_set_status(set_id: str, status: str) -> dict:
    """Mark a test draft, ready (takeable) or archived (hidden)."""
    with expected_errors():
        repo.set_test_set_status(set_id, status)
        return {"set_id": set_id, "status": status}


# ---------------- timed sittings ----------------

@mcp.tool()
def start_test_session(set_id: str, student: str, app: str | None = None) -> SessionStarted:
    """
    Start a sitting of a ready test for a student. Returns the session id
    and the test WITHOUT answers. The app runs the clock; submit with
    submit_test_session.
    """
    with expected_errors():
        return repo.start_test_session(set_id, student, app)


@mcp.tool()
def submit_test_session(
    session_id: str,
    answers: dict[str, str | list[str]],
    flagged: list[str] | None = None,
    seconds_by_item: dict[str, float] | None = None,
) -> SessionResult:
    """
    Finish a sitting: grade it, save every question as a timed attempt,
    and return points and counts by section, domain and topic, plus each
    question's result (with the accepted answers, now that it's over).
    Free responses are saved as needing review, not guessed at.

    Args:
        answers: {item_id: response}: a label ("B"), labels ("A,C" or
                 ["A", "C"]) for select-all, or typed text/number;
                 leave out unanswered items
        flagged: item ids the student marked as unsure (right + flagged
                 counts as "shaky")
        seconds_by_item: optional time spent per item
    """
    with expected_errors():
        return repo.submit_test_session(session_id, answers, flagged, seconds_by_item)


# ---------------- attempts & progress ----------------

@mcp.tool()
def record_attempt(attempt: AttemptIn, app: str | None = None) -> Created:
    """
    Save one answered practice question for a student.

    reasoning: "strong" (right, sound reasoning first try), "shaky" (right
    answer, weak reasoning or a guess), or "missed" (wrong).
    """
    with expected_errors():
        return repo.record_attempt(attempt, app)


@mcp.tool()
def list_attempts(student: str, subject: str | None = None, limit: int = 50) -> list[Attempt]:
    """A student's most recent attempts (newest first, up to 500)."""
    with expected_errors():
        return repo.list_attempts(student, subject, limit)


@mcp.tool()
def get_progress(student: str, subject: str | None = None, days: int = 90,
                 group_by: str = "topic") -> Progress:
    """
    A student's progress over the last `days`, grouped by "topic" (e.g.
    SAT skill) or "domain" (e.g. SAT domain / course unit): counts of
    strong / shaky / missed answers, accuracy in practice vs. timed tests,
    and average time. focus_next lists up to three groups with the highest
    share of shaky + missed answers (at least 3 tries each).
    """
    with expected_errors():
        return repo.get_progress(student, subject, days, group_by)


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    """For the hosting platform's health checks. No auth, no data."""
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok"})


def main() -> None:
    """Entry point for the `learner-mcp` command.

        learner-mcp          stdio (MCP Inspector, local agents)
        learner-mcp --http   streamable HTTP at /mcp, access key required

    HTTP settings (environment):
        LEARNER_MCP_API_KEYS  required, see learner_mcp/auth.py
        HOST                     default 0.0.0.0
        PORT                     default 8000 (most hosts set this for you)
    """
    import os
    import sys

    if "--http" not in sys.argv[1:]:
        mcp.run()
        return

    import uvicorn

    from learner_mcp.auth import ApiKeyMiddleware, load_keys

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    app = ApiKeyMiddleware(
        mcp.streamable_http_app(json_response=True, stateless_http=True, host=host),
        load_keys(),
    )
    uvicorn.run(app, host=host, port=port, proxy_headers=True)


if __name__ == "__main__":
    main()
