"""Tests for MCP-level SANS workflow helpers."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from sans_pilot import data_tools, main
from sans_pilot.datasets import PreparedData
from sans_pilot.schemas import DatasetPipeline, UploadDataSource


def _write_sans_csv(path: Path, *, intensity: float = 1.0) -> None:
  rows = ["Q,I,dI"]
  rows.extend(f"{q / 100:.2f},{intensity},0.1" for q in range(1, 11))
  path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_typed_sans_tools_are_registered_and_legacy_tools_are_removed():
  tools = asyncio.run(main.mcp.list_tools())
  tool_by_name = {tool.name: tool for tool in tools}
  tool_names = set(tool_by_name)
  assert "describe-sans-capabilities" in tool_names
  assert "list-supported-sans-formats" in tool_names
  assert "list-uploaded-sans-files" in tool_names
  assert "inspect-sans-data" in tool_names
  assert "plot-sans-data" in tool_names
  assert "process-sans-data" in tool_names
  assert "list-sans-models" in tool_names
  assert "get-sans-model-parameters" in tool_names
  assert "list-structure-factors" in tool_names
  assert "get-polydispersity-options" in tool_names
  assert "fit-sans-model" in tool_names
  assert "scan-sans-dmax" in tool_names
  assert "invert-sans-pr" in tool_names
  assert "list-sans-examples" in tool_names
  assert "inspect-sans-example" in tool_names
  assert "simulate-sans-data" in tool_names
  assert "simulate-sans-pair" in tool_names
  assert "read-sans-artifact" in tool_names
  assert "describe-possibilities" not in tool_names
  assert "list-uploaded-files" not in tool_names
  assert "get-model-parameters" not in tool_names
  assert "get-structure-factor-parameters" not in tool_names
  assert "get-polydisperse-parameters" not in tool_names
  assert "list-analyses" not in tool_names
  assert "run-analysis" not in tool_names
  upload_description = tool_by_name["list-uploaded-sans-files"].description or ""
  assert "Always call this first" in upload_description
  assert "latest/recent" in upload_description


def test_uploaded_file_listing_is_user_scoped_and_newest_first(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  other_dir = uploads / "user-2"
  user_dir.mkdir(parents=True)
  other_dir.mkdir(parents=True)
  older = user_dir / "old-id__older.csv"
  newer = user_dir / "new-id__simulated_latest.csv"
  hidden_other_user = other_dir / "other-id__private.csv"
  _write_sans_csv(older)
  _write_sans_csv(newer)
  _write_sans_csv(hidden_other_user)
  os.utime(older, (1_000, 1_000))
  os.utime(newer, (2_000, 2_000))

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setattr(data_tools, "get_user_id_from_request", lambda: "user-1")

  result = data_tools.list_uploaded_sans_files()

  assert [item["original_name"] for item in result] == [
    "simulated_latest.csv",
    "older.csv",
  ]
  assert all("private.csv" not in item["original_name"] for item in result)
  assert all(item["content_validated"] is False for item in result)
  assert all(item["validation_scope"] == "extension_only" for item in result)


def test_typed_pipeline_is_validated_through_mcp_transport():
  result = asyncio.run(
    main.mcp.call_tool(
      "inspect-sans-data",
      {
        "pipeline": {
          "primary": {
            "kind": "simulation",
            "model": "sphere",
            "parameters": {"radius": 50},
            "points": 10,
            "seed": 42,
          }
        }
      },
    )
  )

  assert result.structured_content is not None
  assert result.structured_content["analysis"] == "data_inspection"
  assert result.structured_content["source"]["truth"]["radius"] == 50


def test_inspect_sans_data_returns_bounded_metadata(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  input_file = user_dir / "sample.csv"
  _write_sans_csv(input_file)

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setattr(data_tools, "get_user_id_from_request", lambda: "user-1")

  result = data_tools.inspect_sans_data(
    DatasetPipeline(
      primary=UploadDataSource(kind="upload", file="sample.csv"),
    )
  )

  assert result["source"]["file_name"] == "sample.csv"
  assert result["data"]["points_total"] == 10
  assert result["data"]["has_intensity_errors"] is True
  assert result["data"]["has_q_resolution"] is False


def test_render_data_only_plot_never_configures_or_fits_model(tmp_path, monkeypatch):
  q = np.linspace(0.01, 0.1, 10)
  data = SimpleNamespace(
    x=q,
    y=np.linspace(10.0, 1.0, 10),
    dy=np.full(10, 0.1),
    dx=np.full(10, 0.001),
    dxl=None,
    dxw=None,
    mask=np.zeros(10, dtype=bool),
    qmin=float(q.min()),
    qmax=float(q.max()),
  )
  calls: dict[str, Any] = {}

  class Figure:
    def update_layout(self, **kwargs):
      calls["layout"] = kwargs

    def write_image(self, path):
      Path(path).write_bytes(b"png")

  class Fitter:
    def set_data(self, value):
      calls["data"] = value

    def set_model(self, *_args, **_kwargs):
      raise AssertionError("plot-only workflow must not configure a model")

    def fit(self, *_args, **_kwargs):
      raise AssertionError("plot-only workflow must not perform a fit")

    def fit_bayesian(self, *_args, **_kwargs):
      raise AssertionError("plot-only workflow must not perform a Bayesian fit")

    def plot_results(self, **kwargs):
      calls["plot"] = kwargs
      return Figure()

  monkeypatch.setattr(
    data_tools,
    "prepare_dataset",
    lambda _pipeline, user_id: PreparedData(
      data=data,
      preprocessing=[],
      warnings=[],
      source={"kind": "upload", "file_name": "sample.csv"},
    ),
  )
  monkeypatch.setattr(data_tools, "SANSFitter", Fitter)
  output_path = tmp_path / "sans_data_plot.png"

  result = data_tools._render_data_only_plot(
    DatasetPipeline(
      primary=UploadDataSource(kind="upload", file="sample.csv"),
    ),
    user_id="user-1",
    output_path=str(output_path),
    log_scale=False,
  )

  assert calls["data"] is data
  assert calls["plot"] == {
    "show_residuals": False,
    "log_scale": False,
    "show": False,
  }
  assert calls["layout"] == {"height": 500, "width": 900}
  assert output_path.read_bytes() == b"png"
  assert result["configuration"] == {
    "log_scale": False,
    "fit_performed": False,
    "fit_curve_included": False,
    "residuals_included": False,
  }
  assert result["data"]["has_intensity_errors"] is True
  assert result["data"]["has_q_resolution"] is True


def test_plot_sans_data_returns_summary_and_image(tmp_path, monkeypatch):
  captured: dict[str, Any] = {}

  def fake_render(pipeline, *, user_id, output_path, log_scale):
    captured["pipeline"] = pipeline
    captured["user_id"] = user_id
    captured["output_path"] = output_path
    captured["log_scale"] = log_scale
    Path(output_path).write_bytes(b"png")
    return {
      "source": {"kind": "upload", "file_name": "sample.csv"},
      "configuration": {
        "log_scale": log_scale,
        "fit_performed": False,
      },
      "artifacts": [{"name": "sans_data_plot.png", "mime_type": "image/png"}],
    }

  async def run_inline(worker, *args, **_kwargs):
    return worker(*args)

  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setattr(data_tools, "get_user_id_from_request", lambda: "user-1")
  monkeypatch.setattr(data_tools, "_render_data_only_plot", fake_render)
  monkeypatch.setattr(data_tools, "run_cancellable_worker", run_inline)
  monkeypatch.setattr(
    data_tools,
    "create_run_directory",
    lambda _operation: tmp_path,
  )

  pipeline = DatasetPipeline(
    primary=UploadDataSource(kind="upload", file="sample.csv"),
  )

  response = asyncio.run(data_tools.plot_sans_data(pipeline, log_scale=False))

  assert response.structured_content is not None
  assert response.structured_content["configuration"]["fit_performed"] is False
  assert captured["pipeline"] == pipeline
  assert captured["user_id"] == "user-1"
  assert captured["log_scale"] is False
  assert (
    response.structured_content["artifacts"][0]["name"]
    == Path(captured["output_path"]).name
  )
  assert response.structured_content["artifacts"][0]["uri"].startswith(
    "sans-pilot://artifact/"
  )
  assert any(item.type == "image" for item in response.content)


def test_process_sans_data_returns_csv_only_when_explicitly_requested(
  tmp_path,
  monkeypatch,
):
  def fake_process(
    _pipeline,
    *,
    user_id,
    output_path,
    include_processed_csv,
  ):
    assert user_id == "user-1"
    if include_processed_csv:
      Path(output_path).write_text("Q,I\n", encoding="utf-8")
    return {
      "analysis": "data_processing",
      "configuration": {"processed_csv_included": include_processed_csv},
      "artifacts": (
        [{"name": "processed_sans_data.csv", "mime_type": "text/csv"}]
        if include_processed_csv
        else []
      ),
    }

  async def run_inline(worker, *args, **_kwargs):
    return worker(*args)

  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setattr(data_tools, "get_user_id_from_request", lambda: "user-1")
  monkeypatch.setattr(data_tools, "_process_sans_data", fake_process)
  monkeypatch.setattr(data_tools, "run_cancellable_worker", run_inline)
  monkeypatch.setattr(data_tools, "create_run_directory", lambda _name: tmp_path)
  pipeline = DatasetPipeline(
    primary=UploadDataSource(kind="upload", file="sample.csv"),
  )

  compact = asyncio.run(data_tools.process_sans_data(pipeline))
  with_file = asyncio.run(
    data_tools.process_sans_data(pipeline, include_processed_csv=True)
  )

  assert compact["configuration"] == {"processed_csv_included": False}
  assert with_file["artifacts"][0]["uri"].startswith("sans-pilot://artifact/")
