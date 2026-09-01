"""File handling helpers for the MCP server."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp.server.dependencies import get_http_request
from starlette.requests import Request


def get_upload_dir() -> Path:
  """Get the base upload directory from environment."""
  return Path(os.environ.get("UPLOAD_DIR", "/uploads"))


def get_uploads_dir(user_id: str | None = None) -> Path:
  """Get the uploads directory, optionally scoped to a user."""
  data_dir = get_upload_dir()
  if user_id:
    return data_dir / user_id
  return data_dir


def get_user_id_from_request() -> str | None:
  """Extract user ID from the current HTTP request headers."""
  try:
    request: Request = get_http_request()
  except RuntimeError:
    return None
  return request.headers.get("x-user-id")


def resolve_uploaded_path(path_or_name: str, user_id: str | None = None) -> Path:
  """Resolve a file path or name to an absolute path within uploads.

  Args:
    path_or_name: Absolute path, relative path, or filename
    user_id: Optional user ID to scope the uploads directory

  Returns:
    Resolved absolute path to the file

  Raises:
    ValueError: If filename is ambiguous (multiple matches)
    FileNotFoundError: If file cannot be found
  """
  p = Path(path_or_name)
  uploads_dir = get_uploads_dir(user_id).resolve()

  if p.is_absolute():
    candidate = p.resolve()
    if not candidate.is_relative_to(uploads_dir):
      raise ValueError(
        f"Uploaded file path must be within the current user's upload directory: "
        f"{uploads_dir}"
      )
    if candidate.is_file():
      return candidate
    raise FileNotFoundError(f"Uploaded file '{path_or_name}' does not exist.")

  # Direct relative path within uploads dir
  direct_path = (uploads_dir / p).resolve()
  if not direct_path.is_relative_to(uploads_dir):
    raise ValueError("Uploaded file path cannot leave the upload directory.")
  if direct_path.is_file():
    return direct_path

  # Search by filename
  matches = [match for match in uploads_dir.rglob(p.name) if match.is_file()]
  if len(matches) == 1:
    return matches[0]
  if len(matches) > 1:
    raise ValueError(
      f"Ambiguous filename '{p.name}' (found {len(matches)} matches). "
      "Use the full relative path returned by list-uploaded-sans-files."
    )

  raise FileNotFoundError(
    f"Uploaded file '{path_or_name}' not found under {uploads_dir}"
  )


def list_user_uploads(
  *,
  user_id: str | None,
  extensions: set[str] | None,
  limit: int,
) -> list[dict[str, Any]]:
  """List current-user uploads without reading or exposing file contents."""
  uploads_dir = get_uploads_dir(user_id)
  candidates: list[tuple[float, Path, int]] = []

  for file_path in uploads_dir.rglob("*"):
    if not file_path.is_file():
      continue
    extension = file_path.suffix.lower().lstrip(".")
    if extensions is not None and extension not in extensions:
      continue
    stat = file_path.stat()
    candidates.append((stat.st_mtime, file_path, stat.st_size))

  results: list[dict[str, Any]] = []
  for modified_time, file_path, size in sorted(candidates, reverse=True):
    stored_name = file_path.name
    original_name = stored_name.split("__", 1)[-1]
    results.append(
      {
        "original_name": original_name,
        "file": str(file_path.relative_to(uploads_dir)),
        "extension": file_path.suffix.lower().lstrip("."),
        "bytes": size,
        "modified_at": datetime.fromtimestamp(modified_time, tz=UTC).isoformat(),
      }
    )
    if len(results) >= limit:
      break
  return results
