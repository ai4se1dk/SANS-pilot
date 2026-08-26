"""Data loading and preprocessing helpers for SANS analyses."""

from __future__ import annotations

import numbers
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sans_fitter import data_ops

_DATA_OPERATIONS: dict[str, Any] = {
  "add": data_ops.add,
  "subtract": data_ops.subtract,
  "multiply": data_ops.multiply,
  "divide": data_ops.divide,
}


@dataclass(slots=True)
class PreparedData:
  """A fit-ready dataset plus its preprocessing provenance and warnings."""

  data: Any
  preprocessing: list[dict[str, Any]]
  warnings: list[str]


def _warning_messages(captured: list[warnings.WarningMessage]) -> list[str]:
  """Return unique warning messages while preserving their order."""
  result: list[str] = []
  for warning in captured:
    message = str(warning.message)
    if message not in result:
      result.append(message)
  return result


def prepare_data(
  *,
  input_file: str | Path,
  auxiliary_files: dict[str, str | Path] | None = None,
  data_operations: list[dict[str, Any]] | None = None,
) -> PreparedData:
  """Load a primary dataset and apply an ordered preprocessing pipeline."""
  auxiliary_files = auxiliary_files or {}
  data_operations = data_operations or []
  preprocessing: list[dict[str, Any]] = []
  loaded_auxiliary: dict[str, Any] = {}

  with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    data = data_ops.load(str(input_file))

    for index, operation_config in enumerate(data_operations):
      if not isinstance(operation_config, dict):
        raise TypeError(f"Data operation {index + 1} must be an object.")

      unknown_keys = set(operation_config) - {"operation", "operand", "scalar"}
      if unknown_keys:
        unknown = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Data operation {index + 1} has unknown fields: {unknown}.")

      operation_name = operation_config.get("operation")
      if not isinstance(operation_name, str) or operation_name not in _DATA_OPERATIONS:
        available = ", ".join(_DATA_OPERATIONS)
        raise ValueError(
          f"Data operation {index + 1} has invalid operation "
          f"'{operation_name}'. Available: {available}."
        )

      has_operand = "operand" in operation_config
      has_scalar = "scalar" in operation_config
      if has_operand == has_scalar:
        raise ValueError(
          f"Data operation {index + 1} must provide exactly one of "
          "'operand' or 'scalar'."
        )

      if has_operand:
        alias = operation_config["operand"]
        if not isinstance(alias, str) or not alias.strip():
          raise TypeError(
            f"Data operation {index + 1} operand must be a non-empty alias."
          )
        alias = alias.strip()
        if alias not in auxiliary_files:
          available = ", ".join(sorted(auxiliary_files)) or "<none>"
          raise ValueError(
            f"Data operation {index + 1} references unknown auxiliary file "
            f"'{alias}'. Available aliases: {available}."
          )
        if alias not in loaded_auxiliary:
          loaded_auxiliary[alias] = data_ops.load(str(auxiliary_files[alias]))
        operand = loaded_auxiliary[alias]
        provenance: dict[str, Any] = {
          "operation": operation_name,
          "operand": alias,
        }
      else:
        scalar = operation_config["scalar"]
        if not isinstance(scalar, numbers.Real) or isinstance(scalar, bool):
          raise TypeError(f"Data operation {index + 1} scalar must be numeric.")
        operand = float(scalar)
        provenance = {"operation": operation_name, "scalar": operand}

      data = _DATA_OPERATIONS[operation_name](data, operand)
      preprocessing.append(provenance)

  return PreparedData(
    data=data,
    preprocessing=preprocessing,
    warnings=_warning_messages(captured),
  )


def _has_real_values(value: Any) -> bool:
  """Return whether an optional scientific array contains real nonzero data."""
  if value is None:
    return False
  array = np.asarray(value, dtype=float)
  return bool(array.size and np.any(np.isfinite(array) & (array != 0)))


def inspect_data(data: Any, *, source_path: str | Path | None = None) -> dict[str, Any]:
  """Return bounded metadata about a fit-ready SANS dataset."""
  x = np.asarray(data.x, dtype=float)
  y = np.asarray(data.y, dtype=float)
  points_total = int(x.size)

  valid = np.isfinite(x) & np.isfinite(y) & (x > 0)
  mask = getattr(data, "mask", None)
  if mask is not None:
    mask_array = np.asarray(mask, dtype=bool)
    if mask_array.shape == valid.shape:
      valid &= ~mask_array

  full_q = x[np.isfinite(x) & (x > 0)]
  qmin = float(getattr(data, "qmin", np.min(full_q)))
  qmax = float(getattr(data, "qmax", np.max(full_q)))
  fit_index = valid & (x >= qmin) & (x <= qmax)

  result: dict[str, Any] = {
    "points_total": points_total,
    "points_fitted": int(np.sum(fit_index)),
    "masked_or_invalid_points": int(points_total - np.sum(valid)),
    "full_q_range": {
      "min": float(np.min(full_q)),
      "max": float(np.max(full_q)),
    },
    "fit_q_range": {"min": qmin, "max": qmax},
    "has_intensity_errors": _has_real_values(getattr(data, "dy", None)),
    "has_q_resolution": any(
      _has_real_values(getattr(data, attribute, None))
      for attribute in ("dx", "dxl", "dxw")
    ),
  }
  if source_path is not None:
    path = Path(source_path)
    result["file_name"] = path.name
    result["file_format"] = path.suffix.lower().lstrip(".") or "unknown"
  return result


def apply_q_range(
  fitter: Any,
  *,
  q_min: float | None,
  q_max: float | None,
) -> None:
  """Apply an optional fit Q range to a configured fitter."""
  if q_min is None and q_max is None:
    return
  fitter.set_q_range(qmin=q_min, qmax=q_max)
