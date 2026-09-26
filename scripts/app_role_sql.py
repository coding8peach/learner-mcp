"""Print the SQL that creates (or updates) the database login the
learner-mcp server uses, with the password from DATABASE_URL in .env.
Paste the output into the Supabase SQL editor, after scripts/schema.sql.

    uv run python scripts/app_role_sql.py

The login can read and write the "learner" tables and nothing else:
no question banks, no other schemas. It can delete only people and
their own history (attempts, test sittings), for "remove this person".
"""
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

url = urlsplit(dotenv_values(".env")["DATABASE_URL"])
role = url.username.split(".")[0]
password = unquote(url.password).replace("'", "''")
tables = ["test_sets", "test_sections", "test_items", "test_sessions", "attempts", "people"]
deletable = ["people", "attempts", "test_sessions"]   # removing a person erases their history

print(f"""
-- login for the learner-mcp server
do $$ begin
  if exists (select from pg_roles where rolname = '{role}') then
    alter role {role} with login password '{password}';
  else
    create role {role} with login password '{password}';
  end if;
end $$;

grant usage on schema learner to {role};
grant select, insert, update on {", ".join("learner." + t for t in tables)} to {role};
grant delete on {", ".join("learner." + t for t in deletable)} to {role};

-- keep Supabase's public API out
revoke all on schema learner from anon, authenticated;
revoke all on {", ".join("learner." + t for t in tables)} from anon, authenticated;
""")
for t in tables:
    print(f'drop policy if exists "app can use" on learner.{t};')
    print(f'create policy "app can use" on learner.{t} for all to {role} using (true) with check (true);')
print()
