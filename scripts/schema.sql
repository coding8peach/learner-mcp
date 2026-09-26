-- learner-mcp: tests, sessions and attempts for any subject.
-- Everything lives in its own "learner" schema, apart from question banks.
-- Safe to run more than once.

create schema if not exists learner;

-- A test: one or more timed sections of questions
create table if not exists learner.test_sets (
    id          uuid primary key default gen_random_uuid(),
    title       text not null,
    subject     text not null default 'general',   -- e.g. 'sat-rw', 'biology'
    source      text not null default 'manual',    -- bank | upload | manual
    status      text not null default 'ready'
                check (status in ('draft', 'ready', 'archived')),
    created_by  text,                               -- app or person
    scoring     jsonb not null default '{}',       -- future: scaled scores, adaptive routing
    meta        jsonb not null default '{}',
    created_at  timestamptz not null default now()
);

create table if not exists learner.test_sections (
    id                  uuid primary key default gen_random_uuid(),
    set_id              uuid not null references learner.test_sets(id) on delete cascade,
    position            integer not null,
    title               text not null,
    time_limit_seconds  integer,                    -- null = untimed
    unique (set_id, position)
);

create table if not exists learner.test_items (
    id           uuid primary key default gen_random_uuid(),
    section_id   uuid not null references learner.test_sections(id) on delete cascade,
    position     integer not null,
    item_ref     text,               -- where it came from, e.g. 'sat:61228830'
    kind         text not null default 'single_choice'
                 check (kind in ('single_choice', 'multi_choice', 'numeric', 'short_text', 'free_response')),
    domain_code  text,               -- broader group, e.g. an SAT domain or a course unit
    domain       text,
    topic_code   text,               -- e.g. an SAT skill or a lesson
    topic        text,
    tags         text[] not null default '{}',
    difficulty   text,
    points       numeric not null default 1,
    passage      text,               -- HTML or plain text
    stem         text not null,
    choices      jsonb not null default '[]',   -- [{"label": "A", "content": "..."}]
    answers      jsonb not null default '[]',   -- accepted answers; empty = not auto-graded
    tolerance    numeric,            -- numeric questions: allowed difference
    explanation  text,
    figure_urls  jsonb not null default '[]',
    meta         jsonb not null default '{}',
    unique (section_id, position)
);

-- One sitting of a test by one student
create table if not exists learner.test_sessions (
    id           uuid primary key default gen_random_uuid(),
    set_id       uuid not null references learner.test_sets(id) on delete cascade,
    student      text not null,
    app          text,
    started_at   timestamptz not null default now(),
    finished_at  timestamptz,
    answers      jsonb not null default '{}',
    score        jsonb
);

-- Every answered question, from practice or a timed test
create table if not exists learner.attempts (
    id               uuid primary key default gen_random_uuid(),
    created_at       timestamptz not null default now(),
    student          text not null,
    app              text,
    subject          text not null default 'general',
    item_ref         text,
    kind             text,
    domain_code      text,
    domain           text,
    topic_code       text,
    topic            text,
    difficulty       text,
    mode             text not null default 'practice' check (mode in ('practice', 'timed')),
    session_id       uuid references learner.test_sessions(id) on delete set null,
    first_answer     text,
    final_answer     text,
    correct_first    boolean,
    correct_final    boolean,
    reasoning        text check (reasoning in ('strong', 'shaky', 'missed')),
    needs_review     boolean not null default false,   -- e.g. free responses awaiting grading
    points_earned    numeric,
    points_possible  numeric,
    coaching_rounds  integer,
    found_evidence   boolean,
    flagged          boolean,
    seconds          numeric,
    meta             jsonb not null default '{}'
);

create index if not exists attempts_student_time  on learner.attempts (student, created_at desc);
create index if not exists attempts_student_topic on learner.attempts (student, subject, topic_code);
create index if not exists attempts_student_domain on learner.attempts (student, subject, domain_code);
create index if not exists sessions_student       on learner.test_sessions (student, started_at desc);

-- People who can sign in to the apps. Added by a parent; no self sign-up.
-- Passcodes are salted hashes; emails are never stored, only a keyed
-- fingerprint (HMAC-SHA256 with LEARNER_EMAIL_KEY) for matching.
create table if not exists learner.people (
    username       text primary key check (username ~ '^[a-z0-9][a-z0-9_.-]{1,31}$'),
    display_name   text,
    role           text not null default 'student' check (role in ('student', 'parent')),
    passcode_hash  text,
    email_fp       text unique,
    active         boolean not null default true,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    last_sign_in   timestamptz
);

-- Row-level security on: nothing is readable through Supabase's public API
alter table learner.test_sets     enable row level security;
alter table learner.test_sections enable row level security;
alter table learner.test_items    enable row level security;
alter table learner.test_sessions enable row level security;
alter table learner.attempts      enable row level security;
alter table learner.people        enable row level security;
