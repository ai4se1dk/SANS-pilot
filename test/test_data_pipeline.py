"""Tests for SANS data preparation and inspection helpers."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest
from sasdata.dataloader.data_info import Data1D

from sans_pilot.analyses import _data_pipeline


def _data(*, intensity: float = 10.0, error: float | None = 1.0) -> Data1D:
  q = np.linspace(0.01, 0.2, 10)
  dy = None if error is None else np.full_like(q, error)
  data = Data1D(
    x=q,
    y=np.full_like(q, intensity),
    dy=dy,
  )
  dynamic_data = cast(Any, data)
  dynamic_data.qmin = float(q.min())
  dynamic_data.qmax = float(q.max())
  dynamic_data.mask = np.zeros(q.size, dtype=bool)
  return data


def test_prepare_data_applies_ordered_scalar_operations(monkeypatch):
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda _: _data())

  prepared = _data_pipeline.prepare_data(
    input_file="sample.csv",
    data_operations=[
      {"operation": "subtract", "scalar": 2},
      {"operation": "divide", "scalar": 4},
    ],
  )

  np.testing.assert_allclose(prepared.data.y, 2.0)
  np.testing.assert_allclose(prepared.data.dy, 0.25)
  assert prepared.preprocessing == [
    {"operation": "subtract", "scalar": 2.0},
    {"operation": "divide", "scalar": 4.0},
  ]


@pytest.mark.parametrize(
  ("operation", "scalar", "expected_y", "expected_dy"),
  [
    ("add", 2, 12, 1),
    ("subtract", 2, 8, 1),
    ("multiply", 2, 20, 2),
    ("divide", 2, 5, 0.5),
  ],
)
def test_prepare_data_supports_every_scalar_operation(
  monkeypatch,
  operation,
  scalar,
  expected_y,
  expected_dy,
):
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda _: _data())

  prepared = _data_pipeline.prepare_data(
    input_file="sample.csv",
    data_operations=[{"operation": operation, "scalar": scalar}],
  )

  np.testing.assert_allclose(prepared.data.y, expected_y)
  np.testing.assert_allclose(prepared.data.dy, expected_dy)


def test_prepare_data_uses_auxiliary_alias(monkeypatch):
  datasets = {
    "sample.csv": _data(intensity=10),
    "background.csv": _data(intensity=3, error=0.5),
  }
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda name: datasets[name])

  prepared = _data_pipeline.prepare_data(
    input_file="sample.csv",
    auxiliary_files={"background": "background.csv"},
    data_operations=[{"operation": "subtract", "operand": "background"}],
  )

  np.testing.assert_allclose(prepared.data.y, 7.0)
  np.testing.assert_allclose(prepared.data.dy, np.sqrt(1.0**2 + 0.5**2))
  assert prepared.preprocessing == [{"operation": "subtract", "operand": "background"}]


@pytest.mark.parametrize("operation", ["add", "subtract", "multiply", "divide"])
def test_prepare_data_supports_every_dataset_operation(monkeypatch, operation):
  sample = _data(intensity=10, error=1)
  background = _data(intensity=2, error=0.5)
  datasets = {"sample.csv": sample, "background.csv": background}
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda name: datasets[name])

  prepared = _data_pipeline.prepare_data(
    input_file="sample.csv",
    auxiliary_files={"background": "background.csv"},
    data_operations=[{"operation": operation, "operand": "background"}],
  )

  expected = {
    "add": 12,
    "subtract": 8,
    "multiply": 20,
    "divide": 5,
  }
  np.testing.assert_allclose(prepared.data.y, expected[operation])


@pytest.mark.parametrize(
  "operation, message",
  [
    ({"operation": "power", "scalar": 2}, "invalid operation"),
    ({"operation": "add"}, "exactly one"),
    (
      {"operation": "add", "operand": "background", "scalar": 2},
      "exactly one",
    ),
    ({"operation": "add", "scalar": True}, "must be numeric"),
  ],
)
def test_prepare_data_rejects_invalid_operations(monkeypatch, operation, message):
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda _: _data())

  with pytest.raises((TypeError, ValueError), match=message):
    _data_pipeline.prepare_data(
      input_file="sample.csv",
      auxiliary_files={"background": "background.csv"},
      data_operations=[operation],
    )


def test_prepare_data_rejects_unknown_auxiliary_alias(monkeypatch):
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda _: _data())

  with pytest.raises(ValueError, match="unknown auxiliary file"):
    _data_pipeline.prepare_data(
      input_file="sample.csv",
      data_operations=[{"operation": "subtract", "operand": "background"}],
    )


def test_prepare_data_surfaces_mismatched_q_grid_error(monkeypatch):
  sample = _data()
  background = _data()
  background.x = background.x + 0.005
  datasets = {"sample.csv": sample, "background.csv": background}
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda name: datasets[name])

  with pytest.raises(ValueError, match="same Q grid"):
    _data_pipeline.prepare_data(
      input_file="sample.csv",
      auxiliary_files={"background": "background.csv"},
      data_operations=[{"operation": "subtract", "operand": "background"}],
    )


def test_prepare_data_collects_uncertainty_and_resolution_warnings(monkeypatch):
  sample = _data()
  sample.dx = np.full(10, 0.001)
  background = _data(error=None)
  datasets = {"sample.csv": sample, "background.csv": background}
  monkeypatch.setattr(_data_pipeline.data_ops, "load", lambda name: datasets[name])

  prepared = _data_pipeline.prepare_data(
    input_file="sample.csv",
    auxiliary_files={"background": "background.csv"},
    data_operations=[{"operation": "subtract", "operand": "background"}],
  )

  assert any("no intensity uncertainties" in item for item in prepared.warnings)
  assert any("Resolution data" in item for item in prepared.warnings)


def test_inspect_data_reports_q_range_errors_resolution_and_mask():
  data = _data()
  data.dx = np.full(10, 0.001)
  dynamic_data = cast(Any, data)
  dynamic_data.mask[2] = True
  dynamic_data.qmin = float(data.x[1])
  dynamic_data.qmax = float(data.x[-2])

  result = _data_pipeline.inspect_data(data, source_path="measurement.csv")

  assert result["file_name"] == "measurement.csv"
  assert result["file_format"] == "csv"
  assert result["points_total"] == 10
  assert result["points_fitted"] == 7
  assert result["masked_or_invalid_points"] == 1
  assert result["has_intensity_errors"] is True
  assert result["has_q_resolution"] is True
  assert result["fit_q_range"] == {
    "min": pytest.approx(data.x[1]),
    "max": pytest.approx(data.x[-2]),
  }


def test_apply_q_range_only_when_a_bound_is_present():
  class Fitter:
    calls = []

    def set_q_range(self, *, qmin, qmax):
      self.calls.append((qmin, qmax))

  fitter = Fitter()
  _data_pipeline.apply_q_range(fitter, q_min=None, q_max=None)
  _data_pipeline.apply_q_range(fitter, q_min=0.02, q_max=None)
  _data_pipeline.apply_q_range(fitter, q_min=0.02, q_max=0.15)

  assert fitter.calls == [(0.02, None), (0.02, 0.15)]


def test_apply_q_range_propagates_invalid_range_error():
  class Fitter:
    def set_q_range(self, *, qmin, qmax):
      raise ValueError(f"qmin ({qmin}) must be smaller than qmax ({qmax})")

  with pytest.raises(ValueError, match="must be smaller"):
    _data_pipeline.apply_q_range(Fitter(), q_min=0.2, q_max=0.1)
