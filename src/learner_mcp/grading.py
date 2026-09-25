"""Grading for each question kind. Pure functions, no database.

  single_choice  one correct label                    "B"
  multi_choice   every correct label, no extras       "A,C" or ["A", "C"]
  numeric        any accepted value, within tolerance "3/4" == "0.75" == ".75"
  short_text     any accepted text, ignoring case,    "Mitochondria" == "mitochondria."
                 extra spaces and end punctuation
  free_response  not auto-graded: needs review

Returns (correct, points_earned). correct is None when the item can't be
auto-graded (free response, or no accepted answers stored).
"""
import re
from fractions import Fraction

KINDS = ("single_choice", "multi_choice", "numeric", "short_text", "free_response")
DEFAULT_TOLERANCE = 1e-6


def labels(response) -> list[str]:
    """'a, c' / ['A','C'] / 'AC' -> ['A', 'C'] (sorted, unique)."""
    if response is None:
        return []
    if isinstance(response, (list, tuple, set)):
        parts = [str(x) for x in response]
    else:
        text = str(response).strip()
        parts = re.split(r"[,\s;]+", text) if re.search(r"[,\s;]", text) else list(text)
    return sorted({p.strip().upper() for p in parts if p.strip()})


def number(value) -> float | None:
    """'3/4', '.75', '0.75', ' 1,000 ', '-2' -> float; None if not a number."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        if "/" in text:
            return float(Fraction(text))
        return float(text)
    except (ValueError, ZeroDivisionError):
        return None


def text_key(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return text.strip(" .,;:!?\"'")


def response_text(kind: str, response) -> str | None:
    """How a response is stored in attempts (one string)."""
    if response is None or response == "" or response == []:
        return None
    if kind in ("single_choice", "multi_choice"):
        return ",".join(labels(response)) or None
    return str(response).strip() or None


def grade(kind: str, answers: list, response, points: float = 1,
          tolerance: float | None = None, partial_credit: bool = False) -> tuple[bool | None, float | None]:
    if kind == "free_response" or not answers:
        return None, None
    points = float(points)

    if kind == "single_choice":
        ok = labels(response) == labels(answers[:1])
        return ok, points if ok else 0.0

    if kind == "multi_choice":
        want, got = set(labels(answers)), set(labels(response))
        ok = want == got
        if ok or not partial_credit:
            return ok, points if ok else 0.0
        right, wrong = len(want & got), len(got - want)
        return False, max(0.0, points * (right - wrong) / len(want))

    if kind == "numeric":
        got = number(response)
        tol = DEFAULT_TOLERANCE if tolerance is None else float(tolerance)
        ok = got is not None and any(
            (a := number(x)) is not None and abs(a - got) <= tol for x in answers
        )
        return ok, points if ok else 0.0

    if kind == "short_text":
        ok = bool(text_key(response)) and text_key(response) in {text_key(a) for a in answers}
        return ok, points if ok else 0.0

    raise ValueError(f"Unknown question kind: {kind}")
