"""Live `Embedder` adapter: `all-MiniLM-L6-v2` (384-dim) via `fastembed` on ONNX Runtime.

Exempt from unit-test coverage (see `pyproject.toml` / `scripts/check.py` OMIT lists):
calls a local model runtime that downloads a ~90MB ONNX model on first use. Unit tests
inject a fake `Embedder` via the Protocol instead, mirroring `baml_digester` /
`baml_extractor`. The model is the same one the operator attests worked in
logseq-navigator, run through ONNX Runtime rather than `sentence-transformers` so torch
(hundreds of MB) never enters this feather-light project (→ scouting F14, F17).
"""

from __future__ import annotations

import numpy as np
from fastembed import TextEmbedding

_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class FastembedEmbedder:
    """Lazily constructs the `TextEmbedding` model (heavy first-use download) and L2-
    normalizes each row so downstream dot products are cosine similarities directly."""

    def __init__(self) -> None:
        self._model: TextEmbedding | None = None

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            self._model = TextEmbedding(model_name=_MODEL)
        vectors = np.array([np.fromiter(v, dtype=float) for v in self._model.embed(texts)])
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return vectors / norms
