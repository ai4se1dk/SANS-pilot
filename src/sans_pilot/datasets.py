"""Shared loading, preprocessing, validation, and inspection for SANS data."""

from __future__ import annotations

import contextlib
import csv
import io
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
from sans_fitter import SANSFitter, data_ops, examples
from sasdata.dataloader.data_info import Data1D
from sasdata.dataloader.loader import Loader

from sans_pilot.files import resolve_uploaded_path
from sans_pilot.runtime import LOADER_LOCK, scientific_runtime
from sans_pilot.schemas import (
  DatasetPipeline,
  DataSource,
  ExampleDataSource,
  SimulationDataSource,
  UploadDataSource,
)

SUPPORTED_1D_FORMATS: tuple[dict[str, Any], ...] = (
  {
    "format": "columnar_text",
    "extensions": ["csv", "txt", "asc"],
    "description": "Columnar Q, I and optional dI/dQ data.",
  },
  {
    "format": "nist_ascii",
    "extensions": ["abs", "cor"],
    "description": "NIST/SasView reduced one-dimensional ASCII data.",
  },
  {
    "format": "sasview_dat",
    "extensions": ["dat"],
    "description": "SasView text data; accepted only when detected as one-dimensional.",
  },
  {
    "format": "cansas_xml",
    "extensions": ["xml"],
    "description": "CanSAS one-dimensional XML.",
  },
  {
    "format": "nxcansas_hdf5",
    "extensions": ["h5", "hdf", "hdf5", "nxs"],
    "description": "NXcanSAS/HDF5; accepted only when the selected dataset is one-dimensional.",
  },
  {
    "format": "anton_paar_pdh",
    "extensions": ["pdh"],
    "description": "Anton Paar reduced SAXS/SANS-style one-dimensional data.",
  },
)

SUPPORTED_1D_EXTENSIONS = frozenset(
  extension
  for format_info in SUPPORTED_1D_FORMATS
  for extension in format_info["extensions"]
)
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
  source: dict[str, Any] = field(default_factory=dict)
  auxiliary_sources: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class LoadedData:
  """One normalized dataset and bounded source provenance."""

  data: Data1D
  provenance: dict[str, Any]


def _warning_messages(captured: list[warnings.WarningMessage]) -> list[str]:
  """Return unique warning messages while preserving their order."""
  result: list[str] = []
  for warning in captured:
    message = str(warning.message)
    if message not in result:
      result.append(message)
  return result


def list_supported_formats() -> list[dict[str, Any]]:
  """Return a copy of the curated reduced one-dimensional format registry."""
  return [dict(item) for item in SUPPORTED_1D_FORMATS]


def is_supported_upload(path: str | Path) -> bool:
  """Return whether a filename has a supported one-dimensional extension."""
  return Path(path).suffix.lower().lstrip(".") in SUPPORTED_1D_EXTENSIONS


def _format_for_extension(extension: str) -> str:
  for format_info in SUPPORTED_1D_FORMATS:
    if extension in format_info["extensions"]:
      return str(format_info["format"])
  return "unknown"


def _normalize_data(data: Any) -> Data1D:
  """Validate and normalize in-memory data through the public fitter API."""
  fitter = SANSFitter()
  with contextlib.redirect_stdout(io.StringIO()):
    fitter.set_data(data)
  return cast(Data1D, fitter.data)


def _load_uploaded_source(
  source: UploadDataSource, *, user_id: str | None
) -> LoadedData:
  path = resolve_uploaded_path(source.file.strip(), user_id=user_id)
  extension = path.suffix.lower().lstrip(".")

  try:
    with LOADER_LOCK:
      datasets = list(Loader().load(str(path)))
      if not datasets:
        fallback = data_ops.load(str(path))
        datasets = [fallback]
  except Exception as exc:
    diagnostic = _text_load_diagnostic(path)
    raise ValueError(
      f"Failed to load SANS data from '{path.name}'.{diagnostic} Loader detail: {exc}"
    ) from exc

  if source.dataset_index is None:
    if len(datasets) != 1:
      raise ValueError(
        f"'{path.name}' contains {len(datasets)} datasets. Set dataset_index "
        f"to select one (0 to {len(datasets) - 1})."
      )
    selected_index = 0
  else:
    selected_index = source.dataset_index
    if selected_index >= len(datasets):
      raise ValueError(
        f"dataset_index {selected_index} is out of range for '{path.name}', "
        f"which contains {len(datasets)} datasets."
      )

  data = _normalize_data(datasets[selected_index])
  return LoadedData(
    data=data,
    provenance={
      "kind": "upload",
      "file_name": path.name,
      "format": _format_for_extension(extension),
      "extension": extension,
      "dataset_index": selected_index,
      "datasets_in_file": len(datasets),
      "data_type": type(datasets[selected_index]).__name__,
    },
  )


def _text_load_diagnostic(path: Path) -> str:
  """Return bounded delimiter/header diagnostics for failed text loading."""
  if path.suffix.lower() not in {".csv", ".txt", ".asc", ".dat"}:
    return ""
  try:
    sample = path.read_text(encoding="utf-8-sig")[:65_536]
  except (OSError, UnicodeError):
    return ""
  if not sample.strip():
    return " The file is empty."
  first_line = next((line for line in sample.splitlines() if line.strip()), "")
  try:
    delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t ").delimiter
  except csv.Error:
    delimiter = "," if "," in first_line else "unknown"
  columns = (
    [column.strip() for column in first_line.split(delimiter)]
    if delimiter != "unknown"
    else [first_line.strip()]
  )
  bounded_columns = columns[:20]
  suffix = " (truncated)" if len(columns) > len(bounded_columns) else ""
  return (
    f" Detected delimiter {delimiter!r} and header columns "
    f"{bounded_columns!r}{suffix}. Expected reduced-1D Q and I columns with "
    "optional dI and dQ; common aliases include q/x, i/intensity/y, "
    "di/dy/error/uncertainty, and dq/dx/resolution."
  )


def _load_example_source(source: ExampleDataSource) -> LoadedData:
  record = examples.get_example(source.name)
  path = Path(examples.example_path(source.name))
  with LOADER_LOCK:
    data = _normalize_data(examples.load(source.name))

  extension = path.suffix.lower().lstrip(".")
  return LoadedData(
    data=data,
    provenance={
      "kind": "example",
      "name": record.name,
      "file_name": record.filename,
      "format": _format_for_extension(extension),
      "extension": extension,
      "model": record.model,
      "tags": list(record.tags),
    },
  )


def _load_simulation_source(source: SimulationDataSource) -> LoadedData:
  data = examples.simulate(
    source.model,
    qmin=source.q_min,
    qmax=source.q_max,
    npoints=source.points,
    noise=source.noise,
    seed=source.seed,
    dq=source.relative_resolution,
    **cast(dict[str, Any], source.parameters),
  )

  return LoadedData(
    data=_normalize_data(data),
    provenance={
      "kind": "simulation",
      "model": source.model,
      "q_min": source.q_min,
      "q_max": source.q_max,
      "points": source.points,
      "noise": source.noise,
      "seed": source.seed,
      "relative_resolution": source.relative_resolution,
      "parameters": dict(source.parameters),
      "truth": dict(getattr(data, "truth", {})),
    },
  )


def load_data_source(source: DataSource, *, user_id: str | None) -> LoadedData:
  """Load one typed source without allowing uploaded paths to escape user scope."""
  if isinstance(source, UploadDataSource):
    return _load_uploaded_source(source, user_id=user_id)
  if isinstance(source, ExampleDataSource):
    return _load_example_source(source)
  if isinstance(source, SimulationDataSource):
    return _load_simulation_source(source)
  raise TypeError(f"Unsupported data source type: {type(source).__name__}.")


def _apply_data_operations(
  data: Any,
  operations: list[dict[str, Any]],
  *,
  load_operand: Callable[[str], Any],
) -> tuple[Any, list[dict[str, Any]]]:
  """Apply already ordered operations using a caller-provided source loader."""
  preprocessing: list[dict[str, Any]] = []

  for operation_config in operations:
    operation_name = operation_config["operation"]
    alias = operation_config.get("operand")
    if alias is not None:
      operand = load_operand(alias)
      provenance: dict[str, Any] = {
        "operation": operation_name,
        "operand": alias,
      }
    else:
      operand = operation_config["scalar"]
      provenance = {"operation": operation_name, "scalar": operand}

    data = _DATA_OPERATIONS[operation_name](data, operand)
    preprocessing.append(provenance)

  return data, preprocessing


def prepare_dataset(
  pipeline: DatasetPipeline,
  *,
  user_id: str | None,
) -> PreparedData:
  """Resolve and execute a strict dataset pipeline for typed MCP tools."""
  auxiliary_sources: dict[str, dict[str, Any]] = {}
  loaded_auxiliary: dict[str, LoadedData] = {}

  with scientific_runtime(), warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    primary = load_data_source(pipeline.primary, user_id=user_id)

    def load_operand(alias: str) -> Any:
      if alias not in loaded_auxiliary:
        loaded_auxiliary[alias] = load_data_source(
          pipeline.auxiliary[alias],
          user_id=user_id,
        )
        auxiliary_sources[alias] = loaded_auxiliary[alias].provenance
      return loaded_auxiliary[alias].data

    operations = [
      operation.model_dump(exclude_none=True) for operation in pipeline.operations
    ]
    data, preprocessing = _apply_data_operations(
      primary.data,
      operations,
      load_operand=load_operand,
    )

    if pipeline.q_min is not None or pipeline.q_max is not None:
      fitter = SANSFitter()
      with contextlib.redirect_stdout(io.StringIO()):
        fitter.set_data(data)
        apply_q_range(fitter, q_min=pipeline.q_min, q_max=pipeline.q_max)
      data = fitter.data
      preprocessing.append(
        {
          "operation": "select_q_range",
          "q_min": pipeline.q_min,
          "q_max": pipeline.q_max,
        }
      )

  return PreparedData(
    data=data,
    preprocessing=preprocessing,
    warnings=_warning_messages(captured),
    source=primary.provenance,
    auxiliary_sources=auxiliary_sources,
  )


def save_processed_data(data: Data1D, output_path: str | Path) -> Path:
  """Write active, valid processed points through sasdata's CSV writer."""
  path = Path(output_path)
  path.parent.mkdir(parents=True, exist_ok=True)
  dynamic_data = cast(Any, data)

  x = np.asarray(data.x, dtype=float)
  y = np.asarray(data.y, dtype=float)
  index = np.isfinite(x) & np.isfinite(y) & (x > 0)
  mask = getattr(dynamic_data, "mask", None)
  if mask is not None and np.asarray(mask).shape == index.shape:
    index &= ~np.asarray(mask, dtype=bool)
  index &= x >= float(dynamic_data.qmin)
  index &= x <= float(dynamic_data.qmax)
  if not np.any(index):
    raise ValueError("No valid points remain in the active Q range.")

  export_data = data.clone_without_data(length=int(np.sum(index)))
  dynamic_export = cast(Any, export_data)
  for attribute in ("x", "y", "dx", "dy", "dxl", "dxw", "lam", "dlam"):
    values = getattr(data, attribute, None)
    if values is None:
      continue
    array = np.asarray(values)
    if array.shape == index.shape:
      setattr(export_data, attribute, array[index])
  dynamic_export.mask = np.zeros(int(np.sum(index)), dtype=bool)
  dynamic_export.qmin = float(np.min(export_data.x))
  dynamic_export.qmax = float(np.max(export_data.x))

  try:
    with LOADER_LOCK:
      Loader().save(str(path), export_data, ".csv")
  except Exception as exc:
    raise ValueError(f"Failed to save processed SANS data: {exc}") from exc
  if not path.is_file() or path.stat().st_size == 0:
    raise ValueError("The processed SANS data writer produced no output file.")
  return path


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
  if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size == 0:
    raise ValueError(
      "SANS data must contain equally sized, non-empty 1D Q and I arrays."
    )
  points_total = int(x.size)

  valid = np.isfinite(x) & np.isfinite(y) & (x > 0)
  mask = getattr(data, "mask", None)
  if mask is not None:
    mask_array = np.asarray(mask, dtype=bool)
    if mask_array.shape == valid.shape:
      valid &= ~mask_array

  full_q = x[np.isfinite(x) & (x > 0)]
  if full_q.size == 0:
    raise ValueError("SANS data contains no finite positive Q values.")
  qmin_value = getattr(data, "qmin", None)
  qmax_value = getattr(data, "qmax", None)
  qmin = float(np.min(full_q) if qmin_value is None else qmin_value)
  qmax = float(np.max(full_q) if qmax_value is None else qmax_value)
  fit_index = valid & (x >= qmin) & (x <= qmax)
  if not np.any(fit_index):
    raise ValueError("SANS data contains no active points in the requested Q range.")
  active_q = x[fit_index]
  active_intensity = y[fit_index]

  has_pinhole_resolution = _has_real_values(getattr(data, "dx", None))
  has_slit_resolution = any(
    _has_real_values(getattr(data, attribute, None)) for attribute in ("dxl", "dxw")
  )

  result: dict[str, Any] = {
    "data_type": type(data).__name__,
    "points_total": points_total,
    "points_active": int(np.sum(fit_index)),
    "masked_or_invalid_points": int(points_total - np.sum(valid)),
    "full_q_range": {
      "min": float(np.min(full_q)),
      "max": float(np.max(full_q)),
    },
    "requested_q_range": {"min": qmin, "max": qmax},
    "actual_q_range": {
      "min": float(np.min(active_q)),
      "max": float(np.max(active_q)),
    },
    "intensity_range": {
      "min": float(np.min(active_intensity)),
      "max": float(np.max(active_intensity)),
    },
    "has_intensity_errors": _has_real_values(getattr(data, "dy", None)),
    "has_q_resolution": has_pinhole_resolution or has_slit_resolution,
    "resolution_type": (
      "slit" if has_slit_resolution else "pinhole" if has_pinhole_resolution else "none"
    ),
    "units": {
      "q": "Å⁻¹",
      "intensity": str(getattr(data, "_yunit", "unknown") or "unknown"),
    },
    "non_positive_intensity_points_active": int(np.sum(active_intensity <= 0)),
  }
  dy = getattr(data, "dy", None)
  if dy is not None and np.asarray(dy).shape == fit_index.shape:
    active_dy = np.asarray(dy, dtype=float)[fit_index]
    finite_dy = active_dy[np.isfinite(active_dy)]
    if finite_dy.size:
      result["uncertainty_range"] = {
        "min": float(np.min(finite_dy)),
        "max": float(np.max(finite_dy)),
      }
  if source_path is not None:
    path = Path(source_path)
    result["file_name"] = path.name
    result["file_format"] = path.suffix.lower().lstrip(".") or "unknown"
  return result


def log_plot_warnings(data: Any, *, log_scale: bool) -> list[str]:
  """Warn when active intensities cannot be represented on a log axis."""
  if not log_scale:
    return []
  summary = inspect_data(data)
  count = summary["non_positive_intensity_points_active"]
  if not count:
    return []
  return [
    f"Logarithmic intensity plotting cannot normally display {count} active "
    "point(s) with I <= 0. They remain available to fitting but are omitted "
    "or clipped by the logarithmic plot renderer."
  ]


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
