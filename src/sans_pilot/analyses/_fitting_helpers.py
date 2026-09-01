"""Formatting and normalization helpers for fitting analyses."""

from __future__ import annotations

import math
import numbers
from collections.abc import Iterable
from typing import Any

_MAX_NORMALIZE_DEPTH = 4
_MAX_COLLECTION_ITEMS = 100
_MAX_FALLBACK_CHARS = 1_000
_NON_ACTIONABLE_WARNING_MESSAGES = frozenset(
  {"Deprecated: use of problem.fitness will be removed at some point"}
)
_NON_ACTIONABLE_WARNING_PREFIXES = ("Support for the 'engine' argument is deprecated",)
_OPTIMIZER_METADATA_FIELDS = (
  "success",
  "status",
  "message",
  "nit",
  "nfev",
  "njev",
  "cost",
  "optimality",
)


def filter_actionable_warnings(messages: Iterable[str]) -> list[str]:
  """Return unique warnings that are useful to the analysis consumer."""
  actionable: list[str] = []
  for raw_message in messages:
    message = raw_message.strip()
    if not message or message in _NON_ACTIONABLE_WARNING_MESSAGES:
      continue
    if message.startswith(_NON_ACTIONABLE_WARNING_PREFIXES):
      continue
    actionable.append(message)
  return list(dict.fromkeys(actionable))


def normalize_scalar(value: Any) -> Any:
  """Normalize scalar scientific/python values for text serialization."""
  if hasattr(value, "item"):
    try:
      value = value.item()
    except Exception:
      pass

  if isinstance(value, bool):
    return value

  if isinstance(value, numbers.Integral):
    return int(value)

  if isinstance(value, numbers.Real):
    numeric_value = float(value)
    if math.isnan(numeric_value):
      return "nan"
    if math.isinf(numeric_value):
      return "inf" if numeric_value > 0 else "-inf"
    return numeric_value

  if isinstance(value, str) or value is None:
    return value

  return value


def _bounded_text(value: Any) -> str:
  """Return a bounded fallback representation for unsupported values."""
  try:
    text = str(value)
  except Exception:
    text = f"<{type(value).__name__}>"

  if len(text) <= _MAX_FALLBACK_CHARS:
    return text
  return f"{text[: _MAX_FALLBACK_CHARS - 3]}..."


def _public_attributes(value: Any) -> dict[str, Any] | None:
  """Read public instance attributes without invoking properties."""
  try:
    return {key: item for key, item in vars(value).items() if not key.startswith("_")}
  except TypeError:
    return None


def normalize_value(
  value: Any,
  *,
  _depth: int = 0,
  _seen: set[int] | None = None,
) -> Any:
  """Recursively normalize values into simple Python data for LLM output."""
  normalized = normalize_scalar(value)
  if normalized is None or isinstance(normalized, (str, int, float, bool)):
    return normalized
  value = normalized

  if _seen is None:
    _seen = set()

  if _depth >= _MAX_NORMALIZE_DEPTH:
    return _bounded_text(value)

  if isinstance(value, dict):
    obj_id = id(value)
    if obj_id in _seen:
      return "<recursive>"

    _seen.add(obj_id)
    try:
      result = {}
      for index, (key, item) in enumerate(value.items()):
        if index >= _MAX_COLLECTION_ITEMS:
          result["<truncated>"] = f"{len(value) - _MAX_COLLECTION_ITEMS} more items"
          break
        normalized_key = str(key)
        if normalized_key in result:
          normalized_key = f"{type(key).__name__}:{normalized_key}"
        result[normalized_key] = normalize_value(item, _depth=_depth + 1, _seen=_seen)
      return result
    finally:
      _seen.remove(obj_id)

  if isinstance(value, (list, tuple, set, frozenset)):
    obj_id = id(value)
    if obj_id in _seen:
      return "<recursive>"

    _seen.add(obj_id)
    try:
      items = list(value)
      if isinstance(value, (set, frozenset)):
        items.sort(key=lambda item: (type(item).__name__, _bounded_text(item)))

      result = [
        normalize_value(item, _depth=_depth + 1, _seen=_seen)
        for item in items[:_MAX_COLLECTION_ITEMS]
      ]
      if len(items) > _MAX_COLLECTION_ITEMS:
        result.append(f"<{len(items) - _MAX_COLLECTION_ITEMS} more items>")
      return result
    finally:
      _seen.remove(obj_id)

  if hasattr(value, "tolist"):
    obj_id = id(value)
    if obj_id in _seen:
      return "<recursive>"

    _seen.add(obj_id)
    try:
      converted = value.tolist()
      if converted is value:
        return "<recursive>"
      return normalize_value(converted, _depth=_depth + 1, _seen=_seen)
    except Exception:
      pass
    finally:
      _seen.remove(obj_id)

  if hasattr(value, "__dict__"):
    attributes = _public_attributes(value)
    if attributes is not None:
      obj_id = id(value)
      if obj_id in _seen:
        return "<recursive>"

      _seen.add(obj_id)
      try:
        return normalize_value(attributes, _depth=_depth + 1, _seen=_seen)
      finally:
        _seen.remove(obj_id)

  return _bounded_text(value)


def build_parameter_export(
  *,
  model: str,
  params: dict[str, dict[str, Any]],
  fit_result: dict[str, Any],
) -> list[list[str]]:
  """Build sasview-like parameter rows for text export."""
  fit_parameters = (
    fit_result.get("parameters", {}) if isinstance(fit_result, dict) else {}
  )
  rows: list[list[str]] = [["model_name", model]]

  def to_text(value: Any, *, none_as: str = "") -> str:
    converted = normalize_scalar(value)
    if converted is None:
      return none_as
    if isinstance(converted, bool):
      return "True" if converted else "False"
    return str(converted)

  rows.append([model, "None", "", "None", "", "", "()"])

  for name, config in params.items():
    fit_param = fit_parameters.get(name, {}) if isinstance(fit_parameters, dict) else {}
    rows.append(
      [
        name,
        to_text(config.get("vary"), none_as="None"),
        to_text(config.get("value")),
        to_text(fit_param.get("stderr"), none_as="None"),
        to_text(config.get("min")),
        to_text(config.get("max")),
        to_text(config.get("expr") if config.get("expr") is not None else "()"),
      ]
    )

  return rows


def serialize_sasview_parameter_values(rows: list[list[str]]) -> str:
  """Serialize rows into SasView compact text format (':' between records)."""
  payload = ":".join(",".join(str(value) for value in row) for row in rows)
  return f"sasview_parameter_values:{payload}"


def format_fit_result(fit_result: Any) -> dict[str, Any]:
  """Convert a raw fit result into a compact, LLM-readable contract."""
  if not isinstance(fit_result, dict):
    return {"raw": normalize_value(fit_result)}

  formatted = {
    key: normalize_value(fit_result[key])
    for key in ("engine", "method", "chisq", "parameters")
    if key in fit_result
  }

  raw_optimizer = fit_result.get("result")
  optimizer_fields = (
    raw_optimizer
    if isinstance(raw_optimizer, dict)
    else _public_attributes(raw_optimizer)
    if raw_optimizer is not None
    else None
  )
  if optimizer_fields:
    optimizer = {
      key: normalize_value(optimizer_fields[key])
      for key in _OPTIMIZER_METADATA_FIELDS
      if key in optimizer_fields
    }
    if optimizer:
      formatted["optimizer"] = optimizer

  return formatted


def format_posterior_summary(posterior: Any) -> dict[str, Any]:
  """Build a compact posterior summary without exposing raw sample arrays."""
  labels = [str(label) for label in posterior.labels]
  parameters: dict[str, Any] = {}
  diagnostics = posterior.diagnostics or {}

  for label in labels:
    parameter = {
      "best": normalize_scalar(posterior.best[label]),
      "mean": normalize_scalar(posterior.mean[label]),
      "median": normalize_scalar(posterior.median[label]),
      "std": normalize_scalar(posterior.std[label]),
      "ci_68": normalize_value(posterior.ci_68[label]),
      "ci_95": normalize_value(posterior.ci_95[label]),
    }
    if label in diagnostics:
      diagnostic = {
        key: normalize_scalar(value)
        for key, value in diagnostics[label].items()
        if key in {"r_hat", "ess"}
      }
      if diagnostic:
        parameter["diagnostics"] = diagnostic
    parameters[label] = parameter

  return {
    "samples": normalize_scalar(posterior.n_samples),
    "parameters": parameters,
  }
