"""Server-rendered HTML routes for the review surface, one module per feature."""

from fastapi import APIRouter

from screen.web import archive, batch, compare, intake_queue, queue

router = APIRouter()
for feature in (queue, compare, archive, batch, intake_queue):
    router.include_router(feature.router)
