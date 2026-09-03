"""Persistent artifact workspaces, manifests, and MCP URI helpers."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import TextContent


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
  path: Path
  user_id: str | None
  mime_type: str
  published_at: float


_ARTIFACT_LOCK = threading.RLock()
_ARTIFACTS: dict[str, PublishedArtifact] = {}
_TOKEN_PATTERN = re.compile(r"[0-9a-f]{32}")


def artifact_root() -> Path:
  """Return the shared root for generated files and token manifests."""
  return Path(os.environ.get("SANS_PILOT_RUNS_DIR", "/tmp/sans-pilot-runs")).resolve()


def _registry_dir() -> Path:
  path = artifact_root() / ".registry"
  path.mkdir(parents=True, exist_ok=True)
  return path


def _manifest_path(token: str) -> Path:
  return _registry_dir() / f"{token}.json"


def _artifact_ttl_seconds() -> float:
  raw_value = os.environ.get("SANS_PILOT_ARTIFACT_TTL_SECONDS", "86400")
  try:
    return max(float(raw_value), 0.0)
  except ValueError:
    return 86400.0


def _is_expired(artifact: PublishedArtifact, now: float) -> bool:
  ttl = _artifact_ttl_seconds()
  return ttl > 0 and now - artifact.published_at > ttl


def _remove_expired_memory_entries(now: float) -> None:
  expired = [
    token for token, artifact in _ARTIFACTS.items() if _is_expired(artifact, now)
  ]
  for token in expired:
    del _ARTIFACTS[token]


def _write_manifest(token: str, artifact: PublishedArtifact) -> None:
  manifest = {
    "version": 1,
    "token": token,
    **{
      **asdict(artifact),
      "path": str(artifact.path),
    },
  }
  destination = _manifest_path(token)
  temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
  temporary.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
  os.replace(temporary, destination)


def _load_manifest(token: str) -> PublishedArtifact | None:
  path = _manifest_path(token)
  try:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("token") != token:
      return None
    artifact_path = Path(manifest["path"]).resolve()
    # Published files must stay under the configured shared artifact root.
    if not artifact_path.is_relative_to(artifact_root()):
      return None
    user_id = manifest.get("user_id")
    mime_type = manifest["mime_type"]
    published_at = float(manifest["published_at"])
    if user_id is not None and not isinstance(user_id, str):
      return None
    if not isinstance(mime_type, str):
      return None
    return PublishedArtifact(
      path=artifact_path,
      user_id=user_id,
      mime_type=mime_type,
      published_at=published_at,
    )
  except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
    return None


def safe_path_component(value: str) -> str:
  """Return a filesystem-safe component for an operation or source alias."""
  result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
  return result or "output"


def create_run_directory(operation_name: str) -> Path:
  """Create an isolated output directory for one MCP operation."""
  output_dir = artifact_root() / safe_path_component(operation_name) / uuid.uuid4().hex
  output_dir.mkdir(parents=True, exist_ok=True)
  return output_dir


def artifact_token(uri_or_token: str) -> str:
  """Extract and validate an opaque token from an artifact URI or bare token."""
  value = uri_or_token.strip()
  prefix = "sans-pilot://artifact/"
  token = value[len(prefix) :] if value.startswith(prefix) else value
  if not _TOKEN_PATTERN.fullmatch(token):
    raise ValueError(
      "Artifact must be a sans-pilot artifact URI or 32-character token."
    )
  return token


def publish_artifact(path: str | Path, *, user_id: str | None) -> str:
  """Publish an artifact with a durable manifest and return its MCP URI."""
  artifact_path = Path(path).resolve()
  if not artifact_path.is_file():
    raise FileNotFoundError(f"Artifact '{artifact_path.name}' does not exist.")
  if not artifact_path.is_relative_to(artifact_root()):
    raise ValueError("Published artifacts must be inside SANS_PILOT_RUNS_DIR.")

  token = uuid.uuid4().hex
  artifact = PublishedArtifact(
    path=artifact_path,
    user_id=user_id,
    mime_type=mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream",
    published_at=time.time(),
  )
  with _ARTIFACT_LOCK:
    _remove_expired_memory_entries(artifact.published_at)
    _write_manifest(token, artifact)
    _ARTIFACTS[token] = artifact
  return f"sans-pilot://artifact/{token}"


def get_published_artifact(
  uri_or_token: str, *, user_id: str | None
) -> PublishedArtifact:
  """Resolve a durable artifact after enforcing expiry and ownership."""
  token = artifact_token(uri_or_token)
  now = time.time()
  with _ARTIFACT_LOCK:
    _remove_expired_memory_entries(now)
    artifact = _ARTIFACTS.get(token)
    if artifact is None:
      artifact = _load_manifest(token)
      if artifact is not None:
        _ARTIFACTS[token] = artifact

  if artifact is None or _is_expired(artifact, now) or not artifact.path.is_file():
    raise FileNotFoundError("Artifact was not found or has expired.")
  if artifact.user_id is not None and artifact.user_id != user_id:
    raise PermissionError("Artifact does not belong to the current user.")
  return artifact


def read_published_artifact(uri_or_token: str, *, user_id: str | None) -> bytes:
  """Read the bytes of an authorized published artifact."""
  return get_published_artifact(uri_or_token, user_id=user_id).path.read_bytes()


def artifact_result(
  summary: dict[str, Any],
  artifacts: dict[str, Path],
  *,
  user_id: str | None,
) -> dict[str, Any] | ToolResult:
  """Add durable URIs and inline generated images for immediate review."""
  uri_by_name = {
    name: publish_artifact(path, user_id=user_id) for name, path in artifacts.items()
  }
  for metadata in summary.get("artifacts", []):
    if isinstance(metadata, dict) and metadata.get("name") in uri_by_name:
      metadata["uri"] = uri_by_name[metadata["name"]]

  image_paths = [path for path in artifacts.values() if path.suffix.lower() == ".png"]
  if not image_paths:
    return summary

  text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
  return ToolResult(
    content=[
      TextContent(type="text", text=text),
      *(Image(path=path).to_image_content() for path in image_paths),
    ],
    structured_content=summary,
  )
