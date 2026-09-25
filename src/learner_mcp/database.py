import atexit
import os
from threading import Lock

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool, PoolTimeout


load_dotenv()

_pool: ConnectionPool | None = None
_pool_lock = Lock()


def _get_pool() -> ConnectionPool:
    """One shared pool per process, opened on first use.

    Reusing connections avoids a fresh TLS + auth handshake on every
    tool call, which is most of the latency against a hosted Postgres.
    """
    global _pool

    if _pool is None:
        with _pool_lock:
            if _pool is None:
                database_url = os.getenv("DATABASE_URL")

                if not database_url:
                    raise RuntimeError("DATABASE_URL is not set")

                pool = ConnectionPool(
                    database_url,
                    min_size=1,
                    max_size=int(os.getenv("DB_POOL_MAX", "5")),
                    # Transaction-mode poolers (e.g. Supabase port 6543)
                    # don't support prepared statements.
                    kwargs={"prepare_threshold": None},
                    # Supabase's pooler closes idle connections on its end.
                    # Test each connection before handing it out (a dead one
                    # is replaced instead of failing the request), and retire
                    # idle ones ourselves before the pooler does.
                    check=ConnectionPool.check_connection,
                    max_idle=60,
                    open=True,
                )

                # Fail once with a clear message instead of retrying
                # (and flooding the log) forever on a bad DATABASE_URL.
                try:
                    pool.wait(timeout=15)
                except PoolTimeout:
                    pool.close()
                    raise RuntimeError(
                        "Can't connect to the database. Check DATABASE_URL "
                        "(user, password, host) and that the database is up. "
                        "Details are in the warnings above."
                    ) from None

                _pool = pool
                atexit.register(_pool.close)

    return _pool


def get_connection():
    """Borrow a pooled connection:

        with get_connection() as conn:
            ...

    The connection goes back to the pool at the end of the block
    (committed on success, rolled back on error).
    """
    return _get_pool().connection()
