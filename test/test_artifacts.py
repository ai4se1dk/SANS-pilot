"""Tests for lazy, user-scoped MCP artifact publication."""

from __future__ import annotations

import asyncio
import base64

import pytest
from fastmcp import Client
from fastmcp.tools import ToolResult
from mcp.types import ImageContent

from sans_pilot.artifacts import (
  artifact_result,
  publish_artifact,
  read_published_artifact,
)


def test_images_are_inline_and_all_artifacts_have_lazy_uris(tmp_path):
  image = tmp_path / "plot.png"
  image.write_bytes(b"png-bytes")
  summary = {
    "analysis": "test",
    "artifacts": [{"name": image.name, "mime_type": "image/png"}],
  }

  result = artifact_result(
    summary,
    {image.name: image},
    user_id="user-1",
  )

  assert isinstance(result, ToolResult)
  assert result.structured_content == summary
  assert any(isinstance(item, ImageContent) for item in result.content)
  assert summary["artifacts"][0]["uri"].startswith("sans-pilot://artifact/")

  token = summary["artifacts"][0]["uri"].rsplit("/", 1)[-1]
  assert read_published_artifact(token, user_id="user-1") == b"png-bytes"
  with pytest.raises(PermissionError):
    read_published_artifact(token, user_id="user-2")


def test_artifact_can_be_read_through_mcp_resources(tmp_path):
  from sans_pilot.main import mcp

  png = tmp_path / "plot.png"
  payload = b"\x89PNG\r\n\x1a\ncontent"
  png.write_bytes(payload)
  uri = publish_artifact(png, user_id=None)

  async def read_resource():
    async with Client(mcp) as client:
      return await client.read_resource(uri)

  result = asyncio.run(read_resource())

  assert len(result) == 1
  assert base64.b64decode(result[0].blob) == payload  # type: ignore[union-attr]
  assert result[0].model_dump(by_alias=True)["mimeType"] == "image/png"
