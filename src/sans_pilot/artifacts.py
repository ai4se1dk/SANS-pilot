"""Per-request artifact workspaces and lazy artifact URI helpers."""

from __future__ import annotations

import mimetypes
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
  path: Path
  user_id: str | None
  mime_type: str
  published_at: float


_ARTIFACT_LOCK = threading.RLock()
_ARTIFACTS: dict[str, PublishedArtifact] = {}


def _artifact_ttl_seconds() -> float:
  raw_value = os.environ.get("SANS_PILOT_ARTIFACT_TTL_SECONDS", "86400")
  try:
    return max(float(raw_value), 0.0)
  except ValueError:
    return 86400.0


def _remove_expired_artifacts(now: float) -> None:
  ttl = _artifact_ttl_seconds()
  expired = [
    token for token, artifact in _ARTIFACTS.items() if now - artifact.published_at > ttl
  ]
  for token in expired:
    del _ARTIFACTS[token]


def safe_path_component(value: str) -> str:
  """Return a filesystem-safe component for an operation or source alias."""
  result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
  return result or "output"


def create_run_directory(operation_name: str) -> Path:
  """Create an isolated output directory for one MCP operation."""
  runs_dir = Path(os.environ.get("SANS_PILOT_RUNS_DIR", "/tmp/sans-pilot-runs"))
  output_dir = runs_dir / safe_path_component(operation_name) / uuid.uuid4().hex
  output_dir.mkdir(parents=True, exist_ok=True)
  return output_dir


def publish_artifact(path: str | Path, *, user_id: str | None) -> str:
  """Publish an artifact and return its opaque MCP resource URI."""
  artifact_path = Path(path).resolve()
  if not artifact_path.is_file():
    raise FileNotFoundError(f"Artifact '{artifact_path.name}' does not exist.")
  token = uuid.uuid4().hex
  mime_type = mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream"
  now = time.monotonic()
  with _ARTIFACT_LOCK:
    _remove_expired_artifacts(now)
    _ARTIFACTS[token] = PublishedArtifact(
      path=artifact_path,
      user_id=user_id,
      mime_type=mime_type,
      published_at=now,
    )
  return f"sans-pilot://artifact/{token}"


def get_published_artifact(token: str, *, user_id: str | None) -> PublishedArtifact:
  """Resolve an opaque artifact after enforcing expiry and ownership."""
  if not re.fullmatch(r"[0-9a-f]{32}", token):
    raise FileNotFoundError("Invalid artifact identifier.")
  with _ARTIFACT_LOCK:
    _remove_expired_artifacts(time.monotonic())
    artifact = _ARTIFACTS.get(token)
  if artifact is None or not artifact.path.is_file():
    raise FileNotFoundError("Artifact was not found or has expired.")
  if artifact.user_id is not None and artifact.user_id != user_id:
    raise PermissionError("Artifact does not belong to the current user.")
  return artifact


def read_published_artifact(token: str, *, user_id: str | None) -> bytes:
  """Read the bytes of an authorized published artifact."""
  return get_published_artifact(token, user_id=user_id).path.read_bytes()


def artifact_result(
  summary: dict[str, Any],
  artifacts: dict[str, Path],
  *,
  user_id: str | None,
) -> dict[str, Any]:
  """Add lazy artifact URIs to an ordinary JSON-compatible tool result.

  Returning a plain dictionary keeps the response compatible with MCP clients
  that reject newer ResourceLink content blocks. Artifact bytes are available
  separately through the registered MCP resource template.
  """
  uri_by_name = {
    name: publish_artifact(path, user_id=user_id) for name, path in artifacts.items()
  }
  for metadata in summary.get("artifacts", []):
    if isinstance(metadata, dict) and metadata.get("name") in uri_by_name:
      metadata["uri"] = uri_by_name[metadata["name"]]
  return summary
