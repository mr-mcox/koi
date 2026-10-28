"""Starting a research batch from the queue page and polling its progress."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse

from screen.api.deps import app_deps, app_state
from screen.research.batch import BatchProgress
from screen.web.common import templates

router = APIRouter()


@router.post("/batch", response_class=HTMLResponse)
def start_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    batch_size: Annotated[int, Form(gt=0)] = 50,
) -> HTMLResponse:
    """Start a research batch and return immediately. The heavy work runs in a
    `BackgroundTasks` callback with its own DB connection, so the HTTP response
    lands before the first turn is spent.

    A second request while a batch is running is rejected with a clear message
    rather than queued or double-run.
    """
    state = app_state(request)
    if state.batch.running:
        return templates.TemplateResponse(
            request,
            "_batch_status.html",
            {
                "status": state.batch,
                "error": "A batch is already running.",
            },
        )
    state.batch = BatchProgress(running=True, total=batch_size)
    engine = app_deps(request).batch_engine
    background_tasks.add_task(
        engine.run, request.app.state.database.db_path, batch_size, state.batch
    )
    return templates.TemplateResponse(request, "_batch_status.html", {"status": state.batch})


@router.get("/batch-status", response_class=HTMLResponse)
def batch_status(request: Request) -> HTMLResponse:
    """Polling endpoint for the currently running (or last completed) batch.
    Rendered as a small partial the queue page swaps in via HTMX."""
    return templates.TemplateResponse(
        request, "_batch_status.html", {"status": app_state(request).batch}
    )
