"""Synchronization helpers for process-global scientific dependencies."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

# sasdata's Loader is a facade over a singleton Registry.  Its reader instances
# are not safe to use concurrently, even when callers construct separate
# Loader objects.
LOADER_LOCK = threading.RLock()

# warnings.catch_warnings mutates process-global warning state in the supported
# Python runtimes.  Scientific calls capture warnings for their response, so
# overlapping capture regions can otherwise attribute one request's warning to
# another request.  This also protects dependency routines which temporarily
# alter warning filters internally (notably Dmax scans).
SCIENTIFIC_RUNTIME_LOCK = threading.RLock()

# Kaleido/Plotly image export uses process-global renderer state.
RENDER_LOCK = threading.RLock()


@contextmanager
def scientific_runtime() -> Iterator[None]:
  """Serialize warning-sensitive calls into the scientific dependency stack."""
  with SCIENTIFIC_RUNTIME_LOCK:
    yield


@contextmanager
def render_runtime() -> Iterator[None]:
  """Serialize static image rendering through Kaleido."""
  with RENDER_LOCK:
    yield
