"""File handling helpers for the MCP server."""

from __future__ import annotations

import os
from pathlib import Path

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
  request: Request = get_http_request()
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
  if p.is_absolute():
    return p

  uploads_dir = get_uploads_dir(user_id)

  # Direct relative path within uploads dir
  direct_path = uploads_dir / p
  if direct_path.exists():
    return direct_path

  # Search by filename
  matches = [match for match in uploads_dir.rglob(p.name) if match.is_file()]
  if len(matches) == 1:
    return matches[0]
  if len(matches) > 1:
    raise ValueError(
      f"Ambiguous filename '{p.name}' (found {len(matches)} matches). "
      "Use the full relative path returned by list-uploaded-files."
    )

  raise FileNotFoundError(
    f"Uploaded file '{path_or_name}' not found under {uploads_dir}"
  )
