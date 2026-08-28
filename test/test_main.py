"""Tests for MCP-level SANS workflow helpers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
from fastmcp.utilities.types import Image

from sans_pilot import main


def _write_sans_csv(path: Path, *, intensity: float = 1.0) -> None:
  rows = ["Q,I,dI"]
  rows.extend(f"{q / 100:.2f},{intensity},0.1" for q in range(1, 11))
  path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_inspect_sans_data_tool_is_registered():
  tools = asyncio.run(main.mcp.list_tools())
  tool_names = {tool.name for tool in tools}
  assert "inspect-sans-data" in tool_names
  assert "plot-sans-data" in tool_names


def test_inspect_sans_data_returns_bounded_metadata(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  input_file = user_dir / "sample.csv"
  _write_sans_csv(input_file)

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setattr(main, "get_user_id_from_request", lambda: "user-1")

  result = cast(Any, main.inspect_sans_data)("sample.csv")

  assert result["file_name"] == "sample.csv"
  assert result["points_total"] == 10
  assert result["has_intensity_errors"] is True
  assert result["has_q_resolution"] is False


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

  monkeypatch.setattr(main.data_ops, "load", lambda _path: data)
  monkeypatch.setattr(main, "SANSFitter", Fitter)
  output_path = tmp_path / "sans_data_plot.png"

  result = main._render_data_only_plot(
    input_path=tmp_path / "sample.csv",
    output_path=output_path,
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
  assert result["plot"] == {
    "type": "data_only",
    "log_scale": False,
    "fit_performed": False,
  }
  assert result["has_intensity_errors"] is True
  assert result["has_q_resolution"] is True


def test_plot_sans_data_returns_summary_and_image(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  _write_sans_csv(user_dir / "sample.csv")
  captured: dict[str, Any] = {}

  def fake_render(*, input_path, output_path, log_scale):
    captured["input_path"] = input_path
    captured["output_path"] = output_path
    captured["log_scale"] = log_scale
    output_path.write_bytes(b"png")
    return {
      "file_name": input_path.name,
      "plot": {
        "type": "data_only",
        "log_scale": log_scale,
        "fit_performed": False,
      },
    }

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path / "runs"))
  monkeypatch.setattr(main, "get_user_id_from_request", lambda: "user-1")
  monkeypatch.setattr(main, "_render_data_only_plot", fake_render)

  response = asyncio.run(cast(Any, main.plot_sans_data)("sample.csv", log_scale=False))

  summary = json.loads(response[0])
  assert summary["plot"]["fit_performed"] is False
  assert captured["input_path"].is_file()
  assert captured["input_path"].parent.name != user_dir.name
  assert captured["log_scale"] is False
  assert isinstance(response[1], Image)
  assert response[1].path == captured["output_path"]


def test_run_analysis_copies_primary_and_auxiliary_inputs(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  _write_sans_csv(user_dir / "sample.csv")
  _write_sans_csv(user_dir / "background.csv", intensity=0.1)

  captured = {}

  def fake_execute(name, parameters):
    captured["name"] = name
    captured["parameters"] = parameters
    return {"fit": {"chisq": 1.25}, "artifacts": {}}

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path / "runs"))
  monkeypatch.setattr(main, "get_user_id_from_request", lambda: "user-1")
  monkeypatch.setattr(main, "execute_analysis", fake_execute)

  response = asyncio.run(
    cast(Any, main.run_analysis)(
      "fitting-with-custom-model",
      {
        "input_file": "sample.csv",
        "auxiliary_files": {"background": "background.csv"},
        "model": "sphere",
        "param_overrides": {},
      },
    )
  )

  parameters = captured["parameters"]
  copied_input = Path(parameters["input_file"])
  copied_background = Path(parameters["auxiliary_files"]["background"])
  assert copied_input.is_file()
  assert copied_background.is_file()
  assert copied_input.parent == copied_background.parent
  assert copied_background.name.startswith("aux_01_background__")
  assert json.loads(response[0]) == {"chisq": 1.25}


def test_concurrent_runs_use_isolated_input_copies(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  _write_sans_csv(user_dir / "sample.csv")
  captured_parameters = []

  def fake_execute(_name, parameters):
    captured_parameters.append(parameters)
    return {"fit": {"chisq": 1.0}, "artifacts": {}}

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path / "runs"))
  monkeypatch.setattr(main, "get_user_id_from_request", lambda: "user-1")
  monkeypatch.setattr(main, "execute_analysis", fake_execute)

  async def run_two():
    request = {
      "input_file": "sample.csv",
      "model": "sphere",
      "param_overrides": {},
    }
    await asyncio.gather(
      cast(Any, main.run_analysis)("fitting-with-custom-model", request),
      cast(Any, main.run_analysis)("fitting-with-custom-model", request),
    )

  asyncio.run(run_two())

  copied_paths = [Path(parameters["input_file"]) for parameters in captured_parameters]
  assert len(copied_paths) == 2
  assert copied_paths[0] != copied_paths[1]
  assert all(path.is_file() for path in copied_paths)


def test_run_analysis_requires_new_input_file_contract():
  try:
    asyncio.run(
      cast(Any, main.run_analysis)(
        "fitting-with-custom-model",
        {"input_csv": "legacy.csv"},
      )
    )
  except ValueError as error:
    assert "parameters.input_file" in str(error)
  else:
    raise AssertionError("Legacy input_csv unexpectedly remained supported")
