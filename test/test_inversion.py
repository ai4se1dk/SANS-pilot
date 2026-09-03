"""Tests for direct model-free P(r) and Dmax services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from pydantic import ValidationError
from sasdata.dataloader.data_info import Data1D

from sans_pilot import inversion
from sans_pilot.datasets import PreparedData
from sans_pilot.schemas import InvertSansPrRequest, ScanSansDmaxRequest


def _data() -> Data1D:
  q = np.geomspace(0.005, 0.25, 30)
  data = Data1D(
    x=q,
    y=np.exp(-q * 20),
    dy=np.full(q.size, 0.02),
    dx=np.full(q.size, 0.001),
  )
  dynamic = cast(Any, data)
  dynamic.qmin = float(q.min())
  dynamic.qmax = float(q.max())
  dynamic.mask = np.zeros(q.size, dtype=bool)
  return data


def _pipeline() -> dict[str, Any]:
  return {"primary": {"kind": "simulation", "model": "sphere", "seed": 42}}


def test_inversion_schema_requires_complete_manual_selection():
  with pytest.raises(ValidationError, match="alpha"):
    InvertSansPrRequest.model_validate(
      {
        "pipeline": _pipeline(),
        "d_max": 120,
        "selection": {"mode": "manual", "n_terms": 10},
      }
    )


class Figure:
  def write_image(self, path):
    Path(path).write_bytes(b"png")


class PrResult:
  d_max = 120.0
  n_terms = 8
  alpha = 0.01
  regularizer = "corrected"
  background = 0.0
  background_fitted = False
  background_err = 0.0
  data_chisq = 20.0
  effective_dof = 6.0
  regularization_penalty = 0.5
  n_points_used = 30
  accepted = np.ones(30, dtype=bool)
  condition_number = 100.0
  rank = 8
  uncertainties_fabricated = False
  n_dropped_points = 0
  rg = 46.5
  i0 = 100.0
  oscillations = 0.1
  positive_fraction = 0.98
  sigma_positive_fraction = 0.94

  def plot_pr(self, *, show):
    assert show is False
    return Figure()

  def plot_fit(self, data, *, show, log_scale):
    assert data is not None
    assert show is False
    assert log_scale is True
    return Figure()

  def save_csv(self, filename):
    Path(filename).write_text("r,P(r),dP(r)\n", encoding="utf-8")


def test_inversion_service_returns_diagnostics_and_opt_in_csv(tmp_path, monkeypatch):
  prepared = PreparedData(
    data=_data(),
    preprocessing=[],
    warnings=[],
    source={"kind": "simulation", "model": "sphere"},
  )
  captured: dict[str, Any] = {}

  def auto_invert(data, **options):
    captured.update(data=data, options=options)
    return PrResult()

  monkeypatch.setattr(inversion, "prepare_dataset", lambda _p, user_id: prepared)
  monkeypatch.setattr(inversion.pr_inversion, "auto_invert", auto_invert)

  request = InvertSansPrRequest.model_validate(
    {
      "pipeline": _pipeline(),
      "d_max": 120,
      "fit_background": False,
      "include_pr_csv": True,
    }
  )
  result = inversion.invert_sans_pr_service(
    request,
    user_id=None,
    output_dir=tmp_path,
  )

  summary = result["summary"]
  assert summary["analysis"] == "pr_inversion"
  assert summary["result"]["rg_angstrom"] == pytest.approx(46.5)
  assert set(result["artifacts"]) == {
    "pr_distribution.png",
    "pr_iq_fit.png",
    "pr_result.csv",
  }
  assert captured["options"]["fit_background"] is False


class Scan:
  n_terms = 8
  d_max_values = np.array([100.0, 120.0, 140.0])
  data_chisq = np.array([3.0, 1.0, 2.0])
  rg = np.array([44.0, 46.0, 46.1])
  i0 = np.array([90.0, 100.0, 100.5])
  oscillations = np.array([0.2, 0.1, 0.4])
  positive_fraction = np.array([0.9, 0.99, 0.8])
  sigma_positive_fraction = np.array([0.85, 0.95, 0.7])
  background = np.zeros(3)
  alpha = np.full(3, 0.01)
  failures = [(130.0, "unstable")]

  def plot(self, *, quantity, show):
    assert quantity == "all"
    assert show is False
    return Figure()


def test_dmax_service_returns_bounded_scan_arrays(tmp_path, monkeypatch):
  prepared = PreparedData(
    data=_data(),
    preprocessing=[],
    warnings=[],
    source={"kind": "simulation", "model": "sphere"},
  )
  monkeypatch.setattr(inversion, "prepare_dataset", lambda _p, user_id: prepared)
  monkeypatch.setattr(inversion.pr_inversion, "explore_dmax", lambda *_a, **_k: Scan())
  request = ScanSansDmaxRequest(
    pipeline=InvertSansPrRequest.model_validate(
      {"pipeline": _pipeline(), "d_max": 120}
    ).pipeline,
    d_max_guess=120,
    d_min=100,
    d_max=140,
    points=3,
  )

  result = inversion.scan_sans_dmax_service(
    request,
    user_id=None,
    output_dir=tmp_path,
  )

  assert result["summary"]["analysis"] == "dmax_scan"
  assert result["summary"]["result"]["d_max_angstrom"] == [100.0, 120.0, 140.0]
  assert result["summary"]["result"]["failures"] == [
    {"d_max_angstrom": 130.0, "message": "unstable"}
  ]
  assert result["artifacts"]["dmax_scan.png"].is_file()
