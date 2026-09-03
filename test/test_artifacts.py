"""Tests for lazy, user-scoped MCP artifact publication."""

from __future__ import annotations

import asyncio
import base64

import pytest
from fastmcp import Client
from fastmcp.tools import ToolResult
from mcp.types import ImageContent

from sans_pilot import artifact_tools, artifacts
from sans_pilot.artifacts import (
  artifact_result,
  publish_artifact,
  read_published_artifact,
)


def test_images_are_inline_and_all_artifacts_have_lazy_uris(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
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


def test_zero_ttl_disables_artifact_token_expiration(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  artifact = tmp_path / "result.csv"
  artifact.write_bytes(b"result")
  clock = [100.0]
  monkeypatch.setenv("SANS_PILOT_ARTIFACT_TTL_SECONDS", "0")
  monkeypatch.setattr(artifacts.time, "monotonic", lambda: clock[0])

  uri = publish_artifact(artifact, user_id="user-1")
  token = uri.rsplit("/", 1)[-1]
  clock[0] = 10_000_000.0

  assert read_published_artifact(token, user_id="user-1") == b"result"


def test_artifact_manifest_survives_memory_cache_loss(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  artifact = tmp_path / "result.csv"
  artifact.write_bytes(b"persisted")
  uri = publish_artifact(artifact, user_id="user-1")
  artifacts._ARTIFACTS.clear()

  assert read_published_artifact(uri, user_id="user-1") == b"persisted"


def test_read_artifact_tool_returns_chunked_text(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setattr(artifact_tools, "get_user_id_from_request", lambda: "user-1")
  csv = tmp_path / "result.csv"
  csv.write_text("Q,I\n1,2\n3,4\n", encoding="utf-8")
  uri = publish_artifact(csv, user_id="user-1")

  first = artifact_tools.read_sans_artifact(uri, offset=0, limit=6)
  second = artifact_tools.read_sans_artifact(
    uri, offset=first["next_offset"], limit=100
  )

  assert first["text"] == "Q,I\n1,"
  assert first["complete"] is False
  assert second["complete"] is True
  assert first["text"] + second["text"] == "Q,I\n1,2\n3,4\n"


def test_artifact_can_be_read_through_mcp_resources(tmp_path, monkeypatch):
  from sans_pilot.main import mcp

  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
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
