# learner-mcp

An MCP server for **everything about the learner**, for any subject: their
timed tests, every answer they give, and their progress. It pairs with
content servers like sat-mcp: sat-mcp is *what* is learned, learner-mcp is
*who* is learning. Apps like Sidekick use it to save tests, run graded timed
sittings, record practice attempts, and show each student what to work on next.

## Tools

| Tool | What it does |
|---|---|
| `create_test_set` | Save a test: sections (optionally timed) of questions. From a question bank, an uploaded PDF, or by hand. |
| `list_test_sets` / `get_test_set` | Browse tests. Answers are hidden unless `include_answers=True` (review screens only). |
| `set_test_set_status` | `draft` (needs review), `ready` (takeable) or `archived`. |
| `start_test_session` | Begin a sitting; returns the test **without answers**. |
| `submit_test_session` | Grade it here, save each question as a timed attempt, return points and counts by section, domain and topic. |
| `record_attempt` | Save one practice answer: `strong`, `shaky` (right but shaky reasoning/guess) or `missed`. |
| `get_progress` | Per topic or per domain: strong / shaky / missed, practice vs. timed accuracy, average time, and **focus_next**. |
| `list_attempts` | Recent history. |
| `recommend_practice` | A personalized plan: how many questions of each topic, at what difficulty. Weak topics get the most; new and strong ones still get a share. Returns topics, not questions, so it works with any question source. |
| `get_seen_items` | Questions a student already answered, to skip repeats or bring back missed ones. |

### Questions

| Kind | Student answers | Graded as |
|---|---|---|
| `single_choice` | one label | exact label |
| `multi_choice` | several labels (`"A,C"`) | all correct and no extras (optional partial credit) |
| `numeric` | a number | any accepted value within a tolerance; `3/4` = `0.75` = `.75` |
| `short_text` | a word or phrase | any accepted text, ignoring case, spacing and end punctuation |
| `free_response` | anything | not auto-graded: saved as *needs review* |

Every question has `points` (default 1), an optional two-level grouping,
**domain** (e.g. an SAT domain or a course unit) above **topic** (an SAT
skill or a lesson), and free `tags`. Tests also carry a `scoring` field,
reserved for scaled scores and adaptive sections later. Nothing here is tied
to one subject or exam.

## Setup

1. In the Supabase SQL editor, run `scripts/schema.sql` (creates the
   `learner` schema and tables; safe to rerun).
2. Put the app login in `.env` (see `.env.example`), then run
   `uv run python scripts/app_role_sql.py` and paste its output into the
   SQL editor. That login can read/write only the `learner` tables.
3. `uv sync`

## Run

    uv run learner-mcp            # stdio (MCP Inspector, local agents)
    uv run learner-mcp --http     # HTTP at /mcp, access key required

Access keys work like sat-mcp: `uv run python scripts/new_api_key.py sidekick`,
put the whole `name:key` line in `LEARNER_MCP_API_KEYS` on the server, and
give the app only the key part. `/health` is open for health checks.

## Tests

    uv run pytest

runs the grading and validation tests. The database tests run only when
`TEST_DATABASE_URL` points at a **throwaway** Postgres (with `scripts/schema.sql`
and the app login applied), so they can never touch real data. GitHub Actions
does exactly that on every push (`.github/workflows/tests.yml`).

## Environment

| Variable | |
|---|---|
| `DATABASE_URL` | the `learner`-only login |
| `LEARNER_MCP_API_KEYS` | `name:key,name:key` (HTTP mode) |
| `DB_POOL_MAX` | max pooled connections (default 5) |
| `HOST` / `PORT` | HTTP bind address (defaults `0.0.0.0` / `8000`) |
