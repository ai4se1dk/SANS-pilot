"""Tests for the thin fitting MCP adapter."""

from __future__ import annotations

import asyncio
from typing import Any

from sans_pilot import fit_tools
from sans_pilot.fitting import _run_fit
from sans_pilot.schemas import FitSansModelRequest


def _request() -> FitSansModelRequest:
  return FitSansModelRequest.model_validate(
    {
      "pipeline": {"primary": {"kind": "simulation", "model": "sphere", "seed": 42}},
      "model": {"kind": "atomic", "model": "sphere"},
      "parameters": {"radius": {"value": 40, "vary": True}},
    }
  )


def test_fit_settings_are_passed_to_sans_fitter_without_method_policy():
  calls: dict[str, Any] = {}

  class Fitter:
    def fit(self, **kwargs):
      calls.update(kwargs)
      return {"engine": kwargs["engine"], "method": kwargs["method"]}

  request = _request().model_copy(
    update={
      "fit": _request().fit.model_copy(update={"engine": "lmfit", "method": "leastsq"})
    }
  )

  result = _run_fit(Fitter(), request)  # type: ignore[arg-type]

  assert calls == {"engine": "lmfit", "method": "leastsq"}
  assert result == {"engine": "lmfit", "method": "leastsq"}


def test_fit_tool_returns_structured_summary_and_resource_links(tmp_path, monkeypatch):
  plot = tmp_path / "fit_plot.png"
  table = tmp_path / "fit_results.csv"
  plot.write_bytes(b"png")
  table.write_text("Q,I\n", encoding="utf-8")
  captured: dict[str, Any] = {}

  def fake_fit(request, *, user_id, output_dir):
    captured.update(request=request, user_id=user_id, output_dir=output_dir)
    return {
      "summary": {
        "schema_version": "1.0",
        "analysis": "model_fit",
        "result": {"chisq": 1.25},
        "artifacts": [
          {"name": plot.name, "mime_type": "image/png"},
          {"name": table.name, "mime_type": "text/csv"},
        ],
      },
      "artifacts": {plot.name: plot, table.name: table},
    }

  async def run_inline(worker, *args, **_kwargs):
    return worker(*args)

  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setattr(fit_tools, "get_user_id_from_request", lambda: "user-1")
  monkeypatch.setattr(fit_tools, "create_run_directory", lambda _name: tmp_path)
  monkeypatch.setattr(fit_tools, "run_typed_fit", fake_fit)
  monkeypatch.setattr(fit_tools, "run_cancellable_worker", run_inline)

  response = asyncio.run(fit_tools.fit_sans_model(_request()))

  assert response.structured_content is not None
  assert response.structured_content["analysis"] == "model_fit"
  assert captured["user_id"] == "user-1"
  artifacts = response.structured_content["artifacts"]
  assert [item["name"] for item in artifacts] == [plot.name, table.name]
  assert all(item["uri"].startswith("sans-pilot://artifact/") for item in artifacts)
  assert any(item.type == "image" for item in response.content)
