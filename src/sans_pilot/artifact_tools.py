"""MCP tools for retrieving persistent analysis artifacts in later turns."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import TextContent
from pydantic import Field

from sans_pilot.artifacts import get_published_artifact
from sans_pilot.files import get_user_id_from_request


def read_sans_artifact(
  uri: str,
  offset: Annotated[int, Field(ge=0)] = 0,
  limit: Annotated[int, Field(ge=1, le=250_000)] = 50_000,
) -> Any:
  """Read a previously published, user-scoped SANS artifact."""
  artifact = get_published_artifact(uri, user_id=get_user_id_from_request())
  size = artifact.path.stat().st_size
  metadata: dict[str, Any] = {
    "uri": uri,
    "name": artifact.path.name,
    "mime_type": artifact.mime_type,
    "bytes": size,
  }

  if artifact.mime_type.startswith("image/"):
    text = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)
    return ToolResult(
      content=[
        TextContent(type="text", text=text),
        Image(path=artifact.path).to_image_content(),
      ],
      structured_content=metadata,
    )

  if artifact.mime_type.startswith("text/") or artifact.path.suffix.lower() in {
    ".csv",
    ".txt",
  }:
    with artifact.path.open("rb") as handle:
      handle.seek(min(offset, size))
      payload = handle.read(limit)
    end = min(offset, size) + len(payload)
    return {
      **metadata,
      "offset": min(offset, size),
      "bytes_returned": len(payload),
      "next_offset": end if end < size else None,
      "complete": end >= size,
      "text": payload.decode("utf-8", errors="replace"),
    }

  raise ValueError(
    f"Artifact MIME type '{artifact.mime_type}' is not supported for model-context reading."
  )


def register_artifact_tools(mcp: FastMCP) -> None:
  mcp.tool(
    name="read-sans-artifact",
    description=(
      "Read a user-scoped artifact URI returned by an earlier sans-pilot call. "
      "Images are returned as image content. CSV/text artifacts are returned in "
      "bounded chunks using byte offset and limit. Use this for follow-up analysis "
      "of artifacts from prior conversation turns; do not expose internal URIs as "
      "user download links."
    ),
  )(read_sans_artifact)
