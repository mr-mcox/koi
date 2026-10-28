"""Request-scoped accessors for what `create_app` put on `app.state`.

Both read `request.app.state` rather than being rebuilt per app instance — this keeps
them fixed function references, so route signatures can use a plain module-level
`Annotated` type alias.
"""

import sqlite3
from collections.abc import Generator
from typing import TYPE_CHECKING, cast

from fastapi import Request

if TYPE_CHECKING:
    from screen.api.app import AppDeps, AppState


def get_db(request: Request) -> Generator[sqlite3.Connection]:
    """One connection per request. The only seam a hosted/pooled backend would
    need to replace — routes only ever see a `sqlite3.Connection`."""
    conn = request.app.state.database.connect()
    try:
        yield conn
    finally:
        conn.close()


def app_deps(request: Request) -> AppDeps:
    """The collaborators this app was built with."""
    return cast("AppDeps", request.app.state.deps)


def app_state(request: Request) -> AppState:
    """The mutable state this app's routes and background tasks share."""
    return cast("AppState", request.app.state.live)
