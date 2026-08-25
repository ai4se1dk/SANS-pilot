"""Tests for normalization helpers in fitting-with-custom-model."""

from __future__ import annotations

import types
from typing import Any

import numpy as np
import pytest

from sans_pilot.analyses._fitting_helpers import (
  format_fit_result,
  normalize_scalar,
  normalize_value,
)

# ---------------------------------------------------------------------------
# Scalar normalization
# ---------------------------------------------------------------------------


class TestNormalizeScalar:
  def test_numpy_float_becomes_plain_float(self):
    out = normalize_scalar(np.float64(283.81))
    assert isinstance(out, float)
    assert out == pytest.approx(283.81)

  def test_numpy_int_becomes_plain_int(self):
    out = normalize_scalar(np.int64(7))
    assert isinstance(out, int)
    assert out == 7

  def test_none_is_preserved(self):
    assert normalize_scalar(None) is None

  def test_bool_is_preserved(self):
    assert normalize_scalar(True) is True

  def test_nan_is_stringified(self):
    assert normalize_scalar(float("nan")) == "nan"

  def test_positive_inf_is_stringified(self):
    assert normalize_scalar(float("inf")) == "inf"

  def test_negative_inf_is_stringified(self):
    assert normalize_scalar(float("-inf")) == "-inf"


# ---------------------------------------------------------------------------
# Recursive normalization
# ---------------------------------------------------------------------------


class TestResultNormalization:
  def test_dict_normalized_recursively(self):
    value = {
      "chisq": np.float64(283.81),
      "parameters": {
        "radius": {
          "value": np.float64(440.34),
          "stderr": np.float64(9.86),
          "formatted": "440.3(99)",
        },
        "background": {
          "value": np.float64(0.008625),
          "stderr": None,
          "formatted": "0.00863(13)",
        },
      },
      "status": np.int64(0),
      "warnings": [np.float64(1.5), None],
    }

    out = normalize_value(value)

    assert out == {
      "chisq": pytest.approx(283.81),
      "parameters": {
        "radius": {
          "value": pytest.approx(440.34),
          "stderr": pytest.approx(9.86),
          "formatted": "440.3(99)",
        },
        "background": {
          "value": pytest.approx(0.008625),
          "stderr": None,
          "formatted": "0.00863(13)",
        },
      },
      "status": 0,
      "warnings": [1.5, None],
    }

  def test_object_normalized_recursively(self):
    result_obj = types.SimpleNamespace(
      success=True,
      x=np.array([1.0, 2.0]),
      dx=np.array([0.1, 0.2]),
      stats={"nfev": np.int64(3)},
      state=types.SimpleNamespace(best=np.float64(1.25), _private="skip"),
    )

    out = normalize_value(result_obj)

    assert out["success"] is True
    assert out["x"] == [1.0, 2.0]
    assert out["dx"] == [0.1, 0.2]
    assert out["stats"] == {"nfev": 3}
    assert out["state"] == {"best": 1.25}

  def test_tuple_normalized_recursively(self):
    value = (
      np.array([1.0, 2.0]),
      np.array([[3.0, 4.0]]),
      {"nfev": np.int64(3), "residuals": np.array([0.1, 0.2])},
      "done",
      4,
    )
    out = normalize_value(value)
    assert out == [
      [1.0, 2.0],
      [[3.0, 4.0]],
      {"nfev": 3, "residuals": [0.1, 0.2]},
      "done",
      4,
    ]

  def test_recursive_reference_is_marked(self):
    value: dict[str, Any] = {}
    value["self"] = value

    out = normalize_value(value)

    assert out == {"self": "<recursive>"}

  def test_self_returning_tolist_is_marked_without_recursing(self):
    calls = 0

    class SelfReturningArray:
      def tolist(self):
        nonlocal calls
        calls += 1
        return self

    assert normalize_value(SelfReturningArray()) == "<recursive>"
    assert calls == 1

  def test_set_output_is_deterministic(self):
    assert normalize_value({"beta", "alpha", "gamma"}) == [
      "alpha",
      "beta",
      "gamma",
    ]


# ---------------------------------------------------------------------------
# Numeric edge cases
# ---------------------------------------------------------------------------


class TestNumericEdgeCases:
  def test_normalize_value_nan(self):
    assert normalize_value(float("nan")) == "nan"

  def test_normalize_value_inf(self):
    assert normalize_value(float("inf")) == "inf"

  def test_normalize_value_negative_inf(self):
    assert normalize_value(float("-inf")) == "-inf"

  def test_small_scientific_value_preserved(self):
    out = normalize_value(np.float64(1.388e-06))
    assert out == pytest.approx(1.388e-06)

  def test_large_integer_preserved_exactly(self):
    value = 9_007_199_254_740_993
    assert normalize_value(value) == value


class TestFitResultFormatting:
  def test_bumps_result_excludes_problem_and_parameter_vectors(self):
    problem = types.SimpleNamespace(
      active_model=types.SimpleNamespace(
        Iq=np.arange(200),
        dIq=np.arange(200),
        Iq_calc=np.arange(200),
      )
    )
    optimizer = types.SimpleNamespace(
      x=np.array([1.0, 2.0]),
      dx=np.array([0.1, 0.2]),
      fun=np.float64(4.5),
      success=True,
      status=np.int64(0),
      message="converged",
      nit=np.int64(12),
    )

    out = format_fit_result(
      {
        "engine": "bumps",
        "method": "amoeba",
        "chisq": np.float64(9.6758),
        "parameters": {
          "radius": {
            "value": np.float64(15.14),
            "stderr": np.float64(0.037),
          }
        },
        "problem": problem,
        "result": optimizer,
      }
    )

    assert "problem" not in out
    assert out["optimizer"] == {
      "success": True,
      "status": 0,
      "message": "converged",
      "nit": 12,
    }
    assert "x" not in out["optimizer"]
    assert "dx" not in out["optimizer"]
    assert "fun" not in out["optimizer"]

  def test_scipy_result_excludes_residuals_and_jacobian(self):
    out = format_fit_result(
      {
        "engine": "lmfit",
        "method": "least_squares",
        "chisq": np.float64(5.0),
        "parameters": {},
        "result": {
          "success": np.bool_(True),
          "status": np.int64(1),
          "message": "complete",
          "nfev": np.int64(20),
          "fun": np.arange(200),
          "jac": np.arange(400).reshape(200, 2),
          "cost": np.float64(2.5),
        },
      }
    )

    assert out["optimizer"] == {
      "success": True,
      "status": 1,
      "message": "complete",
      "nfev": 20,
      "cost": 2.5,
    }
    assert "fun" not in out["optimizer"]
    assert "jac" not in out["optimizer"]
