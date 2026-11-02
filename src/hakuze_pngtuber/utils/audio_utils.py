"""Audio math helpers shared by engine, detector and tests."""
from __future__ import annotations

import numpy as np


def block_rms(block: np.ndarray) -> float:
    """RMS level of an audio block (any channels), returned in 0.0..1.0+ range.

    Accepts int or float arrays; converts to float32 mono-mean first.
    """
    if block is None or block.size == 0:
        return 0.0
    data = np.asarray(block, dtype=np.float32)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if data.dtype.kind in "iu":
        pass  # already float32 via astype above
    return float(np.sqrt(np.mean(np.square(data))))


def db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def linear_to_db(lin: float) -> float:
    if lin <= 0.0:
        return -120.0
    return 20.0 * float(np.log10(lin))
