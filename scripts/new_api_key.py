"""Print a new random access key for LEARNER_MCP_API_KEYS.

    uv run python scripts/new_api_key.py sidekick
    -> sidekick:<43 random characters>

Put the whole line in the server's LEARNER_MCP_API_KEYS (comma-separate
several apps); give the app only the part after "sidekick:".
"""
import secrets
import sys

name = sys.argv[1] if len(sys.argv) > 1 else "app"
print(f"{name}:{secrets.token_urlsafe(32)}")
