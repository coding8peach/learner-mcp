"""Access keys for the HTTP server.

Every request must send one of the configured keys:

    Authorization: Bearer <key>        (or)    X-API-Key: <key>

Keys come from LEARNER_MCP_API_KEYS, comma-separated, each optionally
named so you can tell apps apart in the logs and revoke one app
without touching the others:

    LEARNER_MCP_API_KEYS=sidekick:Xy3...,adaptive:Qp9...

Make a key with:  uv run python scripts/new_api_key.py
"""
import hmac
import json
import logging
import os

logger = logging.getLogger("learner_mcp.auth")

OPEN_PATHS = {"/health"}   # for the host's health checks; no data there

# MCP clients that get a 401 go looking for OAuth (discovery documents,
# dynamic client registration). This server uses static keys, not OAuth,
# so answer those with a quiet 404 and the client stops searching.
OAUTH_PATHS = ("/.well-known/", "/register", "/authorize", "/token")
MIN_KEY_LENGTH = 24


def load_keys() -> dict[str, str]:
    """{key: app_name} from LEARNER_MCP_API_KEYS. Refuses short keys."""
    keys = {}
    # Forgive paste slips on hosting dashboards: surrounding quotes,
    # spaces/newlines, or the variable name pasted into the value.
    raw = os.getenv("LEARNER_MCP_API_KEYS", "").strip().strip("\"'")
    if raw.startswith("LEARNER_MCP_API_KEYS="):
        raw = raw.split("=", 1)[1]

    clean = lambda x: x.strip().strip("\"'").strip()  # noqa: E731
    for i, item in enumerate(filter(None, (clean(x) for x in raw.split(","))), 1):
        name, sep, key = item.partition(":")
        if not sep:
            name, key = f"key{i}", item
        name, key = clean(name), clean(key)

        if len(key) < MIN_KEY_LENGTH:
            raise RuntimeError(
                f"API key '{name}' is too short ({len(key)} chars). Use at "
                f"least {MIN_KEY_LENGTH} random characters: "
                "uv run python scripts/new_api_key.py"
            )
        keys[key] = name

    return keys


class ApiKeyMiddleware:
    """Plain ASGI middleware: rejects HTTP requests without a valid key."""

    def __init__(self, app, keys: dict[str, str]):
        if not keys:
            raise RuntimeError(
                "LEARNER_MCP_API_KEYS is not set. The HTTP server won't start "
                "without at least one access key."
            )
        self.app = app
        self.keys = keys

    def _match(self, presented: str) -> str | None:
        # compare against every key in constant time
        found = None
        for key, name in self.keys.items():
            if hmac.compare_digest(presented.encode(), key.encode()):
                found = name
        return found

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            return await self.app(scope, receive, send)

        if scope["path"].startswith(OAUTH_PATHS):
            return await _json(send, 404, {"error": "not found (this server uses access keys, not OAuth)"})

        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        auth = headers.get("authorization", "")
        presented = (
            auth[7:].strip() if auth.lower().startswith("bearer ")
            else headers.get("x-api-key", "").strip()
        )

        app_name = self._match(presented) if presented else None

        if app_name is None:
            client = (scope.get("client") or ("?",))[0]
            logger.warning(
                "Rejected request from %s to %s (%s)", client, scope["path"],
                "wrong key" if presented else "no key sent",
            )
            return await _json(send, 401, {
                "error": "unauthorized",
                "hint": "send the access key as 'Authorization: Bearer <key>'",
            })

        scope.setdefault("state", {})["app_name"] = app_name
        return await self.app(scope, receive, send)


async def _json(send, status: int, payload: dict):
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": json.dumps(payload).encode()})
