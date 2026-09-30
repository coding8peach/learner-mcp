-- learner-mcp: let outside channels (e.g. Google Forms) own sittings.
-- Run once in the Supabase SQL editor. Safe to re-run.

alter table learner.test_sessions
    add column if not exists external_ref text,
    add column if not exists meta jsonb not null default '{}'::jsonb;

-- One sitting per outside id, per app ("gforms:<responseId>" for Bellringer).
create unique index if not exists test_sessions_app_external_ref
    on learner.test_sessions (coalesce(app, ''), external_ref)
    where external_ref is not null;

create index if not exists test_sessions_student_finished
    on learner.test_sessions (student, finished_at desc);
