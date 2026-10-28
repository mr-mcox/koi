"""Process entry point for `uvicorn screen.api.main:app`: loads `.env`, then builds the
production app. Nothing imports this module; tests build apps with `create_app`."""

import os

from screen.env import load_env
from screen.wiring import build_app

load_env()
app = build_app(os.environ)
