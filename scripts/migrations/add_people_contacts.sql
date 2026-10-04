-- learner-mcp: encrypted contact addresses and per-app settings on people.
-- Run once in the Supabase SQL editor. Safe to re-run.

alter table learner.people
    add column if not exists email_enc text,                                  -- encrypted, see contacts.py
    add column if not exists app_settings jsonb not null default '{}'::jsonb; -- {"bellringer": {"forms": true}}
