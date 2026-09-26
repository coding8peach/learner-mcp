-- Adds sign-in accounts (learner.people) to an existing learner-mcp database.
-- Paste into the Supabase SQL editor. Safe to run more than once.
-- (A new database gets all of this from scripts/schema.sql + scripts/app_role_sql.py.)

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
alter table learner.people enable row level security;

-- the learner-mcp server's login (change the name if yours differs)
grant select, insert, update, delete on learner.people to learner_mcp_app;
grant delete on learner.attempts, learner.test_sessions to learner_mcp_app;
drop policy if exists "app can use" on learner.people;
create policy "app can use" on learner.people for all to learner_mcp_app using (true) with check (true);

-- keep Supabase's public API out
revoke all on learner.people from anon, authenticated;
