"""Project-wide pytest configuration.

The BAML runtime has an env var `BAML_ALLOW_MODEL_REQUESTS` which, when
unset/true, permits live LLM calls. Tests must never issue live calls.
The baml-py package reads this env var at runtime; setting it in the
test session means an accidentally live call would surface immediately
rather than silently passing or racking up a real API bill.
"""

import os

# Set explicitly False so tests forbid accidental live model calls.
os.environ.setdefault("BAML_ALLOW_MODEL_REQUESTS", "false")
