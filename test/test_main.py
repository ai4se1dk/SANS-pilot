"""Tests for MCP-level SANS workflow helpers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from sans_pilot import main


def _write_sans_csv(path: Path, *, intensity: float = 1.0) -> None:
  rows = ["Q,I,dI"]
  rows.extend(f"{q / 100:.2f},{intensity},0.1" for q in range(1, 11))
  path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_inspect_sans_data_tool_is_registered():
  tools = asyncio.run(main.mcp.list_tools())
  assert "inspect-sans-data" in {tool.name for tool in tools}


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
