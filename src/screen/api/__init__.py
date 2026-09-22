"""FastAPI backend package. Import `screen.api.app` directly (`from screen.api.app
import app, create_app`) — this file stays empty so importing any submodule
(`screen.api.pool`, `screen.api.scoring`) never pulls in `screen.api.app`'s own import
chain, which reaches back into `screen.research.batch` via `screen.intake.pipeline`.
"""

from __future__ import annotations
