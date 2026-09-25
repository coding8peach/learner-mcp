"""Database access for test sets, sessions and attempts.

Errors a caller can fix (unknown test, bad status...) raise ValueError;
the server turns those into readable tool errors.
"""
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from learner_mcp.database import get_connection
from learner_mcp.grading import grade, response_text
from learner_mcp.models import (
    Attempt,
    AttemptIn,
    Created,
    GroupScore,
    GroupStats,
    Item,
    ItemIn,
    ItemResult,
    PlanItem,
    PracticePlan,
    Progress,
    Section,
    SectionIn,
    SessionResult,
    SessionStarted,
    SeenItem,
    TestSet,
    TestSetSummary,
    TopicIn,
)

MAX_LIMIT = 500
FOCUS_MIN_DONE = 3        # need a few attempts before calling a topic weak
FOCUS_MIN_WEAK_RATE = 0.25


def _uuid(value, what: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        raise ValueError(f"Not a valid {what} id: {value}") from None


def _num(value):
    return float(value) if value is not None else None


# ---------------- test sets ----------------

def create_test_set(*, title: str, subject: str, source: str, sections: list[SectionIn],
                    status: str = "ready", scoring: dict | None = None, meta: dict | None = None,
                    created_by: str | None = None) -> Created:
    if status not in ("draft", "ready"):
        raise ValueError("status must be 'draft' or 'ready'")
    count = 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """insert into learner.test_sets (title, subject, source, status, created_by, scoring, meta)
               values (%s, %s, %s, %s, %s, %s, %s) returning id""",
            (title.strip(), subject.strip() or "general", source, status, created_by,
             Jsonb(scoring or {}), Jsonb(meta or {})),
        )
        set_id = cur.fetchone()[0]
        for s_pos, section in enumerate(sections, 1):
            cur.execute(
                """insert into learner.test_sections (set_id, position, title, time_limit_seconds)
                   values (%s, %s, %s, %s) returning id""",
                (set_id, s_pos, section.title, section.time_limit_seconds),
            )
            section_id = cur.fetchone()[0]
            for i_pos, item in enumerate(section.items, 1):
                _insert_item(cur, section_id, i_pos, item)
                count += 1
    return Created(id=set_id, question_count=count)


def _insert_item(cur, section_id, position: int, item: ItemIn):
    cur.execute(
        """insert into learner.test_items
             (section_id, position, item_ref, kind, domain_code, domain, topic_code, topic, tags,
              difficulty, points, passage, stem, choices, answers, tolerance, explanation,
              figure_urls, meta)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (section_id, position, item.item_ref, item.kind, item.domain_code, item.domain,
         item.topic_code, item.topic, item.tags, item.difficulty, item.points, item.passage,
         item.stem, Jsonb([c.model_dump() for c in item.choices]), Jsonb(item.answers),
         item.tolerance, item.explanation, Jsonb(item.figure_urls), Jsonb(item.meta)),
    )


def list_test_sets(subject: str | None = None, status: str | None = "ready") -> list[TestSetSummary]:
    sql = """
        select s.id, s.title, s.subject, s.source, s.status, s.created_at,
               (select count(*) from learner.test_items i
                  join learner.test_sections x on x.id = i.section_id
                 where x.set_id = s.id) as question_count,
               (select sum(time_limit_seconds) from learner.test_sections x
                 where x.set_id = s.id) as total_seconds
          from learner.test_sets s
         where (%(subject)s::text is null or s.subject = %(subject)s)
           and (%(status)s::text is null or s.status = %(status)s)
         order by s.created_at desc
    """
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"subject": subject, "status": status})
        return [TestSetSummary(**row) for row in cur.fetchall()]


def _item(row: dict, include_answers: bool) -> Item:
    row = dict(row)
    row["points"] = float(row["points"])
    row["tolerance"] = _num(row["tolerance"])
    if not include_answers:
        row["answers"] = None
        row["tolerance"] = None
        row["explanation"] = None
    return Item(**row)


def get_test_set(set_id, include_answers: bool = False) -> TestSet:
    set_id = _uuid(set_id, "test")
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""select id, title, subject, source, status, scoring, meta
                         from learner.test_sets where id = %s""", (set_id,))
        head = cur.fetchone()
        if not head:
            raise ValueError(f"Test not found: {set_id}")
        cur.execute("""select id, position, title, time_limit_seconds from learner.test_sections
                        where set_id = %s order by position""", (set_id,))
        sections = cur.fetchall()
        cur.execute("""select i.* from learner.test_items i
                         join learner.test_sections x on x.id = i.section_id
                        where x.set_id = %s order by x.position, i.position""", (set_id,))
        items = cur.fetchall()

    by_section: dict = {s["id"]: [] for s in sections}
    for row in items:
        by_section[row["section_id"]].append(_item(row, include_answers))
    return TestSet(**head, sections=[Section(**s, items=by_section[s["id"]]) for s in sections])


def set_test_set_status(set_id, status: str) -> None:
    if status not in ("draft", "ready", "archived"):
        raise ValueError("status must be draft, ready or archived")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("update learner.test_sets set status = %s where id = %s",
                    (status, _uuid(set_id, "test")))
        if cur.rowcount == 0:
            raise ValueError(f"Test not found: {set_id}")


# ---------------- sessions ----------------

def start_test_session(set_id, student: str, app: str | None = None) -> SessionStarted:
    test = get_test_set(set_id, include_answers=False)
    if test.status != "ready":
        raise ValueError(f"This test is {test.status}, not ready to take.")
    if not student.strip():
        raise ValueError("student is required")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""insert into learner.test_sessions (set_id, student, app)
                       values (%s, %s, %s) returning id""", (test.id, student.strip(), app))
        session_id = cur.fetchone()[0]
    return SessionStarted(session_id=session_id, test=test)


def _tally(groups: dict, code, name, correct: bool | None, earned: float | None, possible: float):
    g = groups.setdefault(code, {"name": name, "correct": 0, "total": 0, "earned": 0.0, "possible": 0.0})
    if correct is not None:
        g["correct"] += bool(correct)
        g["total"] += 1
        g["earned"] += earned or 0.0
        g["possible"] += possible


def _scores(groups: dict) -> list[GroupScore]:
    return sorted((GroupScore(code=k, name=v["name"], correct=v["correct"], total=v["total"],
                              points_earned=v["earned"], points_possible=v["possible"])
                   for k, v in groups.items() if v["total"]),
                  key=lambda g: (g.name or g.code or ""))


def submit_test_session(session_id, answers: dict, flagged: list[str] | None = None,
                        seconds_by_item: dict[str, float] | None = None) -> SessionResult:
    """Grade a finished sitting, store its attempts, and return the results
    (including the accepted answers, now that the test is over)."""
    session_id = _uuid(session_id, "session")
    flagged_ids = {str(x) for x in (flagged or [])}
    seconds_by_item = {str(k): v for k, v in (seconds_by_item or {}).items()}
    answers = {str(k): v for k, v in (answers or {}).items()}

    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("select * from learner.test_sessions where id = %s for update", (session_id,))
        session = cur.fetchone()
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if session["finished_at"] is not None:
            raise ValueError("This session was already submitted.")
        cur.execute("select subject from learner.test_sets where id = %s", (session["set_id"],))
        subject = cur.fetchone()["subject"]
        cur.execute("""select i.*, x.title as section_title
                         from learner.test_items i
                         join learner.test_sections x on x.id = i.section_id
                        where x.set_id = %s order by x.position, i.position""", (session["set_id"],))
        items = cur.fetchall()

        # Refuse answers for questions that aren't in this test (a wrong id
        # would otherwise be silently scored as a blank), and keep the
        # session open so the app can fix it and submit again.
        known = {str(row["id"]) for row in items}
        unknown = sorted(set(answers) - known)
        if unknown:
            raise ValueError(
                f"{len(unknown)} answer(s) are for questions not in this test: "
                f"{', '.join(unknown[:5])}{'...' if len(unknown) > 5 else ''}. "
                "Use the item ids from start_test_session. Nothing was saved."
            )

        results: list[ItemResult] = []
        sections, domains, topics = {}, {}, {}
        for row in items:
            item_id = str(row["id"])
            response = answers.get(item_id)
            chosen = response_text(row["kind"], response)
            points = float(row["points"])
            correct, earned = grade(row["kind"], row["answers"], response, points,
                                    _num(row["tolerance"]), bool(row["meta"].get("partial_credit")))
            needs_review = correct is None and row["kind"] == "free_response" and chosen is not None
            is_flagged = item_id in flagged_ids
            reasoning = None
            if correct is not None:
                reasoning = "missed" if not correct else ("shaky" if is_flagged else "strong")

            results.append(ItemResult(
                item_id=row["id"], section=row["section_title"], position=row["position"],
                kind=row["kind"], domain_code=row["domain_code"], domain=row["domain"],
                topic_code=row["topic_code"], topic=row["topic"], chosen=chosen,
                answers=row["answers"], correct=correct, points_earned=earned,
                points_possible=points, needs_review=needs_review, flagged=is_flagged,
                reasoning=reasoning,
            ))
            _tally(sections, row["section_title"], row["section_title"], correct, earned, points)
            _tally(domains, row["domain_code"], row["domain"], correct, earned, points)
            _tally(topics, row["topic_code"], row["topic"], correct, earned, points)

            if correct is not None or needs_review:
                cur.execute(
                    """insert into learner.attempts
                         (student, app, subject, item_ref, kind, domain_code, domain, topic_code,
                          topic, difficulty, mode, session_id, first_answer, final_answer,
                          correct_first, correct_final, reasoning, needs_review, points_earned,
                          points_possible, flagged, seconds, meta)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'timed', %s, %s, %s, %s, %s,
                               %s, %s, %s, %s, %s, %s, %s)""",
                    (session["student"], session["app"], subject, row["item_ref"] or f"item:{item_id}",
                     row["kind"], row["domain_code"], row["domain"], row["topic_code"], row["topic"],
                     row["difficulty"], session_id, chosen, chosen, correct, correct, reasoning,
                     needs_review, earned, points, is_flagged, seconds_by_item.get(item_id),
                     Jsonb({"test_item_id": item_id})),
                )

        graded = [r for r in results if r.correct is not None]
        result = SessionResult(
            session_id=session_id,
            correct=sum(1 for r in graded if r.correct),
            graded=len(graded),
            total=len(results),
            needs_review=sum(1 for r in results if r.needs_review),
            points_earned=sum(r.points_earned or 0 for r in graded),
            points_possible=sum(r.points_possible for r in graded),
            sections=_scores(sections), domains=_scores(domains), topics=_scores(topics),
            items=results,
        )
        cur.execute("""update learner.test_sessions
                          set finished_at = now(), answers = %s, score = %s where id = %s""",
                    (Jsonb({"answers": answers, "flagged": sorted(flagged_ids)}),
                     Jsonb({"correct": result.correct, "graded": result.graded, "total": result.total,
                            "points_earned": result.points_earned,
                            "points_possible": result.points_possible,
                            "needs_review": result.needs_review}),
                     session_id))
    return result


# ---------------- attempts & progress ----------------

def record_attempt(attempt: AttemptIn, app: str | None = None) -> Created:
    data = attempt.model_dump()
    data["meta"] = Jsonb(data["meta"])
    cols = list(data) + ["app"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"insert into learner.attempts ({', '.join(cols)}) "
            f"values ({', '.join(['%s'] * len(cols))}) returning id",
            [*data.values(), app],
        )
        return Created(id=cur.fetchone()[0])


def list_attempts(student: str, subject: str | None = None, limit: int = 50) -> list[Attempt]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """select * from learner.attempts
                where student = %s and (%s::text is null or subject = %s)
                order by created_at desc limit %s""",
            (student, subject, subject, limit),
        )
        rows = cur.fetchall()
    out = []
    for row in rows:
        row.pop("session_id", None)
        for k in ("seconds", "points_earned", "points_possible"):
            row[k] = _num(row[k])
        out.append(Attempt(**row))
    return out


def get_progress(student: str, subject: str | None = None, days: int = 90,
                 group_by: str = "topic") -> Progress:
    if group_by not in ("topic", "domain"):
        raise ValueError("group_by must be 'topic' or 'domain'")
    days = max(1, min(int(days), 3650))
    code_col, name_col = (("topic_code", "topic") if group_by == "topic" else ("domain_code", "domain"))
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            select {code_col} as code, max({name_col}) as name,
                   count(*) filter (where not needs_review) as done,
                   count(*) filter (where reasoning = 'strong') as strong,
                   count(*) filter (where reasoning = 'shaky')  as shaky,
                   count(*) filter (where reasoning = 'missed') as missed,
                   count(*) filter (where needs_review) as needs_review,
                   coalesce(avg(case when correct_final then 1.0 else 0.0 end)
                            filter (where correct_final is not null), 0) as accuracy,
                   avg(case when correct_final then 1.0 else 0.0 end)
                       filter (where mode = 'practice' and correct_final is not null) as practice_accuracy,
                   avg(case when correct_final then 1.0 else 0.0 end)
                       filter (where mode = 'timed' and correct_final is not null) as timed_accuracy,
                   avg(seconds) as avg_seconds
              from learner.attempts
             where student = %(student)s
               and created_at > now() - make_interval(days => %(days)s)
               and (%(subject)s::text is null or subject = %(subject)s)
             group by {code_col}
             order by max({name_col}) nulls last
            """,
            {"student": student, "subject": subject, "days": days},
        )
        rows = cur.fetchall()

    review = sum(r.pop("needs_review") for r in rows)
    groups = [GroupStats(**{k: (_num(v) if k in ("accuracy", "practice_accuracy", "timed_accuracy",
                                                   "avg_seconds") else v) for k, v in r.items()})
              for r in rows if r["done"]]

    def weak_rate(g: GroupStats) -> float:
        return (g.shaky + g.missed) / g.done if g.done else 0

    focus = sorted((g for g in groups if g.done >= FOCUS_MIN_DONE and weak_rate(g) >= FOCUS_MIN_WEAK_RATE),
                   key=weak_rate, reverse=True)[:3]
    return Progress(
        student=student, subject=subject, days=days, group_by=group_by,
        total=sum(g.done for g in groups), strong=sum(g.strong for g in groups),
        shaky=sum(g.shaky for g in groups), missed=sum(g.missed for g in groups),
        needs_review=review, groups=groups, focus_next=focus,
    )


# ---------------- practice planning ----------------

def _difficulty(accuracy: float | None) -> str:
    """Stretch students who are doing well; rebuild confidence when not."""
    if accuracy is None:
        return "medium"
    if accuracy < 0.5:
        return "easy"
    if accuracy < 0.8:
        return "medium"
    return "hard"


def _allocate(weights: list[float], total: int, must: list[bool]) -> list[int]:
    """Split `total` questions by weight (largest remainder), giving every
    `must` entry at least one when there's room."""
    n = len(weights)
    counts = [0] * n
    remaining = total
    for i in sorted(range(n), key=lambda i: -weights[i]):
        if must[i] and remaining > 0:
            counts[i] = 1
            remaining -= 1
    if remaining <= 0:
        return counts
    wsum = sum(weights) or 1.0
    shares = [w / wsum * remaining for w in weights]
    extra = [int(s) for s in shares]
    left = remaining - sum(extra)
    for i in sorted(range(n), key=lambda i: -(shares[i] - extra[i]))[:left]:
        extra[i] += 1
    return [c + e for c, e in zip(counts, extra)]


def recommend_practice(student: str, subject: str | None = None, length: int = 10,
                       topics: list | None = None, days: int = 90) -> PracticePlan:
    """How many questions of each topic, at what difficulty, for a
    personalized practice set. Weak topics get the most; new topics and
    strong ones still get a share so nothing is left out or goes stale."""
    length = max(1, min(int(length), 200))
    progress = get_progress(student, subject, days)
    stats = {g.code: g for g in progress.groups}

    universe = [t if isinstance(t, TopicIn) else TopicIn(**t) for t in (topics or [])]
    if not universe:      # no list from the app: plan over what the student has practiced
        universe = [TopicIn(topic_code=g.code, topic=g.name) for g in progress.groups if g.code]
    if not universe:
        raise ValueError("No topics to plan from: pass `topics` (e.g. the question bank's skills).")

    rows, weights, must = [], [], []
    for t in universe:
        g = stats.get(t.topic_code)
        if g is None or g.done < FOCUS_MIN_DONE:
            reason, weight, accuracy = "new", 1.0, (g.accuracy if g else None)
        else:
            weak = (g.shaky + g.missed) / g.done
            reason = "weak" if weak >= FOCUS_MIN_WEAK_RATE else "maintain"
            weight, accuracy = 0.5 + 2.5 * weak, g.accuracy
        rows.append((t, reason, accuracy))
        weights.append(weight)
        must.append(reason == "weak")

    counts = _allocate(weights, length, must)
    order = {"weak": 0, "new": 1, "maintain": 2}
    items = [
        PlanItem(topic_code=t.topic_code, topic=t.topic or (stats[t.topic_code].name if t.topic_code in stats else None),
                 domain_code=t.domain_code, domain=t.domain, count=c,
                 difficulty=_difficulty(accuracy if reason != "new" else None),
                 reason=reason, accuracy=accuracy)
        for (t, reason, accuracy), c in zip(rows, counts) if c > 0
    ]
    items.sort(key=lambda p: (order[p.reason], -p.count, p.topic or p.topic_code))
    return PracticePlan(student=student, subject=subject, length=length, items=items)


def get_seen_items(student: str, subject: str | None = None, days: int | None = None,
                   limit: int = 2000) -> list[SeenItem]:
    """Questions the student has already answered (by item_ref), so new
    sets can skip them, or bring back missed ones on purpose."""
    limit = max(1, min(int(limit), 10000))
    with get_connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select item_ref, count(*) as times, max(created_at) as last_seen,
                   (array_agg(correct_final order by created_at desc))[1] as last_correct
              from learner.attempts
             where student = %(student)s and item_ref is not null
               and (%(subject)s::text is null or subject = %(subject)s)
               and (%(days)s::int is null or created_at > now() - make_interval(days => %(days)s))
             group by item_ref
             order by max(created_at) desc
             limit %(limit)s
            """,
            {"student": student, "subject": subject, "days": days, "limit": limit},
        )
        return [SeenItem(**row) for row in cur.fetchall()]
