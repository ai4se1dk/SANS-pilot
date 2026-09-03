"""Tests for lazy, user-scoped MCP artifact publication."""

from __future__ import annotations

import asyncio
import base64
from urllib.parse import parse_qs, urlsplit

import pytest
from fastmcp import Client
from fastmcp.tools import ToolResult
from mcp.types import ImageContent
from starlette.testclient import TestClient

from sans_pilot import artifact_tools, artifacts
from sans_pilot.artifacts import (
  artifact_download_url,
  artifact_result,
  get_downloadable_artifact,
  publish_artifact,
  read_published_artifact,
)


def test_images_are_inline_and_all_artifacts_have_lazy_uris(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setenv("SANS_PILOT_DOWNLOAD_SIGNING_KEY", "test-signing-key")
  monkeypatch.setenv(
    "SANS_PILOT_PUBLIC_BASE_URL", "https://chat.example/api/sans-artifacts"
  )
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
  assert summary["artifacts"][0]["bytes"] == len(b"png-bytes")
  assert summary["artifacts"][0]["download_url"].startswith(
    "https://chat.example/api/sans-artifacts/"
  )

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
  monkeypatch.setattr(artifacts.time, "time", lambda: clock[0])

  uri = publish_artifact(artifact, user_id="user-1")
  token = uri.rsplit("/", 1)[-1]
  clock[0] = 10_000_000.0

  assert read_published_artifact(token, user_id="user-1") == b"result"


def test_download_url_is_omitted_when_not_configured(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.delenv("SANS_PILOT_PUBLIC_BASE_URL", raising=False)
  monkeypatch.delenv("SANS_PILOT_DOWNLOAD_SIGNING_KEY", raising=False)
  artifact = tmp_path / "result.csv"
  artifact.write_bytes(b"result")

  uri = publish_artifact(artifact, user_id="user-1")

  assert artifact_download_url(uri) is None


def test_signed_download_url_is_stable_and_bound_to_artifact(tmp_path, monkeypatch):
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setenv("SANS_PILOT_ARTIFACT_TTL_SECONDS", "0")
  monkeypatch.setenv("SANS_PILOT_DOWNLOAD_SIGNING_KEY", "test-signing-key")
  monkeypatch.setenv(
    "SANS_PILOT_PUBLIC_BASE_URL", "https://chat.example/api/sans-artifacts"
  )
  artifact = tmp_path / "fit results.csv"
  artifact.write_bytes(b"Q,I\n1,2\n")
  uri = publish_artifact(artifact, user_id="user-1")

  first_url = artifact_download_url(uri)
  second_url = artifact_download_url(uri)

  assert first_url == second_url
  assert first_url is not None
  parsed = urlsplit(first_url)
  token = uri.rsplit("/", 1)[-1]
  signature = parse_qs(parsed.query)["signature"][0]
  assert parsed.path == f"/api/sans-artifacts/{token}/fit%20results.csv"
  artifacts._ARTIFACTS.clear()
  assert (
    get_downloadable_artifact(
      token, filename="fit results.csv", signature=signature
    ).path
    == artifact
  )
  with pytest.raises(PermissionError):
    get_downloadable_artifact(token, filename="other.csv", signature=signature)
  with pytest.raises(PermissionError):
    get_downloadable_artifact(token, filename=artifact.name, signature="0" * 64)


def test_artifact_download_route_streams_signed_file(tmp_path, monkeypatch):
  from sans_pilot.main import mcp

  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setenv("SANS_PILOT_ARTIFACT_TTL_SECONDS", "0")
  monkeypatch.setenv("SANS_PILOT_DOWNLOAD_SIGNING_KEY", "test-signing-key")
  monkeypatch.setenv(
    "SANS_PILOT_PUBLIC_BASE_URL", "http://testserver/api/sans-artifacts"
  )
  artifact = tmp_path / "result.csv"
  artifact.write_bytes(b"Q,I\n1,2\n")
  uri = publish_artifact(artifact, user_id="user-1")
  download_url = artifact_download_url(uri)
  assert download_url is not None

  with TestClient(mcp.http_app()) as client:
    response = client.get(download_url)
    rejected = client.get(download_url.replace("signature=", "signature=bad"))

  assert response.status_code == 200
  assert response.content == artifact.read_bytes()
  assert response.headers["content-type"] == "text/csv; charset=utf-8"
  assert response.headers["content-disposition"].startswith("attachment;")
  assert response.headers["cache-control"] == "private, no-store"
  assert response.headers["x-content-type-options"] == "nosniff"
  assert rejected.status_code == 404


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
  monkeypatch.setenv("SANS_PILOT_DOWNLOAD_SIGNING_KEY", "test-signing-key")
  monkeypatch.setenv(
    "SANS_PILOT_PUBLIC_BASE_URL", "https://chat.example/api/sans-artifacts"
  )
  uri = publish_artifact(csv, user_id="user-1")

  first = artifact_tools.read_sans_artifact(uri, offset=0, limit=6)
  second = artifact_tools.read_sans_artifact(
    uri, offset=first["next_offset"], limit=100
  )

  assert first["text"] == "Q,I\n1,"
  assert first["download_url"].startswith("https://chat.example/api/sans-artifacts/")
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
