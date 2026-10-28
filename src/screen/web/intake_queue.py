"""The intake queue: submit a URL for the background intake worker and watch its rows."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from screen.intake.admission import declined_host_for, declined_submission_message
from screen.store.repo import enqueue_intake_url, list_intake_queue, reset_intake_url_to_pending
from screen.web.common import Conn, templates

router = APIRouter()


@router.post("/intake-queue", response_class=HTMLResponse)
def post_intake_queue(
    request: Request, conn: Conn, url: Annotated[str, Form(min_length=1)]
) -> HTMLResponse:
    """Enqueue one URL for the background intake worker. The insert commits
    before this returns (bearing: queuing is blocking, minimizing lost work) —
    the worker (started once in the app lifespan) picks it up on its own,
    including a URL added while it's mid-batch.

    A declined host (W7) is refused here, the only place it is checked."""
    declined = declined_host_for(url)
    if declined is not None:
        return templates.TemplateResponse(
            request,
            "_intake_queue_panel.html",
            {
                "items": list_intake_queue(conn),
                "submit_error": declined_submission_message(declined),
            },
        )
    enqueue_intake_url(conn, url)
    items = list_intake_queue(conn)
    return templates.TemplateResponse(
        request, "_intake_queue_panel.html", {"items": items, "submit_error": None}
    )


@router.post("/intake-queue/{item_id}/retry", response_class=HTMLResponse)
def retry_intake_url(request: Request, conn: Conn, item_id: str) -> HTMLResponse:
    """Requeue one failed row as pending; the always-on worker picks it up
    on its next poll. A no-op if the row isn't `failed` (e.g. a stale button
    click after the row already advanced)."""
    reset_intake_url_to_pending(conn, item_id)
    items = list_intake_queue(conn)
    return templates.TemplateResponse(request, "_intake_queue_list.html", {"items": items})


@router.get("/intake-queue", response_class=HTMLResponse)
def intake_queue(request: Request, conn: Conn) -> HTMLResponse:
    """The intake queue page: submit a URL, see every queued/running/done/failed
    row and its failure reason — the only intake surface (CLI retired)."""
    items = list_intake_queue(conn)
    return templates.TemplateResponse(
        request, "intake_queue.html", {"items": items, "submit_error": None}
    )
