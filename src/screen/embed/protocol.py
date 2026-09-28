"""Protocol surface for text embedders.

Any object satisfying `Embedder` can be injected wherever digests are embedded. The
live adapter (`FastembedEmbedder`, `all-MiniLM-L6-v2` via ONNX Runtime) and test fakes
both satisfy it. Mirrors `screen.digest.protocol` / `screen.extract.protocol`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed `texts` into a row-major matrix (one row per text). Rows need not be
        unit-normalized — `provisional_ties` normalizes before taking dot products as
        cosine similarity."""
        ...
