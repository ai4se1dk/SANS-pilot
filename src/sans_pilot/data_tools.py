"""Typed MCP tools for loading, inspecting, plotting, and processing SANS data."""

from __future__ import annotations

import asyncio
import contextlib
import io
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field
from sans_fitter import SANSFitter

from sans_pilot.artifacts import artifact_result, create_run_directory
from sans_pilot.datasets import (
  SUPPORTED_1D_EXTENSIONS,
  PreparedData,
  inspect_data,
  list_supported_formats,
  log_plot_warnings,
  prepare_dataset,
  save_processed_data,
)
from sans_pilot.files import (
  get_user_id_from_request,
  list_user_uploads,
)
from sans_pilot.runtime import render_runtime
from sans_pilot.schemas import DatasetPipeline

SCHEMA_VERSION = "1.0"


def describe_sans_capabilities() -> dict[str, Any]:
  """Describe the scientific scope and important limitations of this server."""
  return {
    "schema_version": SCHEMA_VERSION,
    "scope": "Reduced one-dimensional Small-Angle Neutron Scattering analysis",
    "capabilities": [
      "inspect reduced 1D SANS data",
      "plot measured data without fitting",
      "add, subtract, multiply, and divide datasets or scalars",
      "select an active Q range",
      "load curated sans-fitter examples",
      "generate simulated data through sans-fitter",
      "generate matched sample/background simulations on a common Q grid",
      "fit sasmodels form-factor and structure-factor models",
      "scan maximum particle dimension and recover model-free P(r)",
    ],
    "limitations": [
      "2D reduction and fitting are not implemented",
      "SESANS analysis is not implemented",
      "dataset arithmetic requires matching Q grids",
    ],
  }


def list_supported_sans_formats() -> dict[str, Any]:
  """List the curated community formats accepted as reduced 1D I(Q) data."""
  return {
    "schema_version": SCHEMA_VERSION,
    "data_scope": "reduced_1d_iq",
    "formats": list_supported_formats(),
    "type_validation": (
      "DAT and HDF5-family containers are accepted only when the selected "
      "dataset is one-dimensional."
    ),
    "unsupported": ["2D SANS", "SESANS"],
  }


def list_uploaded_sans_files(
  extensions: list[str] | None = None,
  limit: Annotated[int, Field(ge=1, le=200)] = 50,
  supported_only: bool = True,
) -> list[dict[str, Any]]:
  """List newest-first current-user uploads without exposing file contents."""
  normalized_extensions = (
    {extension.lower().lstrip(".") for extension in extensions} if extensions else None
  )
  if supported_only:
    normalized_extensions = (
      set(SUPPORTED_1D_EXTENSIONS)
      if normalized_extensions is None
      else normalized_extensions & SUPPORTED_1D_EXTENSIONS
    )
  uploads = list_user_uploads(
    user_id=get_user_id_from_request(),
    extensions=normalized_extensions,
    limit=limit,
  )
  return [
    {
      **upload,
      "content_validated": False,
      "validation_scope": "extension_only",
    }
    for upload in uploads
  ]


def _dataset_result(
  analysis: str,
  prepared: PreparedData,
  *,
  configuration: dict[str, Any] | None = None,
  artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
  """Build the bounded common result envelope for data operations."""
  return {
    "schema_version": SCHEMA_VERSION,
    "analysis": analysis,
    "source": prepared.source,
    "auxiliary_sources": prepared.auxiliary_sources,
    "data": inspect_data(prepared.data),
    "preprocessing": prepared.preprocessing,
    "configuration": configuration or {},
    "warnings": prepared.warnings,
    "artifacts": artifacts or [],
  }


def inspect_sans_data(pipeline: DatasetPipeline) -> dict[str, Any]:
  """Inspect a typed dataset pipeline without fitting a model."""
  prepared = prepare_dataset(pipeline, user_id=get_user_id_from_request())
  return _dataset_result("data_inspection", prepared)


def _render_data_only_plot(
  pipeline: DatasetPipeline,
  *,
  user_id: str | None,
  output_path: str,
  log_scale: bool,
) -> dict[str, Any]:
  prepared = prepare_dataset(pipeline, user_id=user_id)
  prepared.warnings.extend(log_plot_warnings(prepared.data, log_scale=log_scale))
  fitter = SANSFitter()
  with contextlib.redirect_stdout(io.StringIO()):
    fitter.set_data(prepared.data)
  figure = fitter.plot_results(
    show_residuals=False,
    log_scale=log_scale,
    show=False,
  )
  figure.update_layout(height=500, width=900)
  with render_runtime():
    figure.write_image(output_path)
  return _dataset_result(
    "data_plot",
    prepared,
    configuration={
      "log_scale": log_scale,
      "fit_performed": False,
      "fit_curve_included": False,
      "residuals_included": False,
    },
    artifacts=[{"name": "sans_data_plot.png", "mime_type": "image/png"}],
  )


async def plot_sans_data(
  pipeline: DatasetPipeline,
  log_scale: bool = True,
) -> dict[str, Any]:
  """Plot data from a typed pipeline without selecting or fitting a model."""
  output_dir = create_run_directory("plot-sans-data")
  plot_path = output_dir / "sans_data_plot.png"
  user_id = get_user_id_from_request()
  result = await asyncio.to_thread(
    _render_data_only_plot,
    pipeline,
    user_id=user_id,
    output_path=str(plot_path),
    log_scale=log_scale,
  )
  return artifact_result(result, {plot_path.name: plot_path}, user_id=user_id)


def _process_sans_data(
  pipeline: DatasetPipeline,
  *,
  user_id: str | None,
  output_path: str,
  include_processed_csv: bool,
) -> dict[str, Any]:
  prepared = prepare_dataset(pipeline, user_id=user_id)
  artifacts: list[dict[str, str]] = []
  if include_processed_csv and inspect_data(prepared.data)["resolution_type"] == "slit":
    prepared.warnings.append(
      "The processed CSV artifact cannot preserve slit-smearing resolution "
      "columns. The in-memory processing summary is valid, but do not reuse "
      "the CSV for resolution-smeared fitting."
    )
  if include_processed_csv:
    save_processed_data(prepared.data, output_path)
    artifacts.append({"name": "processed_sans_data.csv", "mime_type": "text/csv"})
  return _dataset_result(
    "data_processing",
    prepared,
    configuration={
      "processed_csv_included": include_processed_csv,
      "output_format": "csv" if include_processed_csv else None,
    },
    artifacts=artifacts,
  )


async def process_sans_data(
  pipeline: DatasetPipeline,
  include_processed_csv: bool = False,
) -> dict[str, Any]:
  """Apply typed preprocessing and optionally return a processed-data file."""
  output_dir = create_run_directory("process-sans-data")
  output_path = output_dir / "processed_sans_data.csv"
  user_id = get_user_id_from_request()
  result = await asyncio.to_thread(
    _process_sans_data,
    pipeline,
    user_id=user_id,
    output_path=str(output_path),
    include_processed_csv=include_processed_csv,
  )
  artifacts = {output_path.name: output_path} if include_processed_csv else {}
  return artifact_result(result, artifacts, user_id=user_id)


def register_data_tools(mcp: FastMCP) -> None:
  """Register the typed data tools on a FastMCP server."""
  mcp.tool(
    name="describe-sans-capabilities",
    description="Describe supported SANS workflows and scientific limitations.",
  )(describe_sans_capabilities)
  mcp.tool(
    name="list-supported-sans-formats",
    description=(
      "List accepted reduced 1D SANS file formats and dimensionality rules. "
      "Call this before deciding whether an uploaded community-format file is usable."
    ),
  )(list_supported_sans_formats)
  mcp.tool(
    name="list-uploaded-sans-files",
    description=(
      "List the current user's uploaded SANS files, newest first, by stored "
      "filename, original filename, modification time, extension, and size. "
      "File contents are not returned. Always call this first when the user "
      "refers to 'my uploads', 'my files', or the latest/recent uploaded file "
      "without providing an exact stored filename."
    ),
  )(list_uploaded_sans_files)
  mcp.tool(
    name="inspect-sans-data",
    description=(
      "Load and inspect an upload, bundled example, or simulation, "
      "with optional ordered arithmetic and Q-range selection. Does not fit a model."
    ),
  )(inspect_sans_data)
  mcp.tool(
    name="plot-sans-data",
    description=(
      "Plot an upload, example, or simulation after optional preprocessing. "
      "Never selects a model, fits a curve, or plots residuals."
    ),
  )(plot_sans_data)
  mcp.tool(
    name="process-sans-data",
    description=(
      "Apply ordered dataset/scalar operations and an optional Q range, then "
      "return a compact summary. Set include_processed_csv only when the user "
      "explicitly requests a reusable file; file contents may otherwise consume "
      "model context in clients without attachment-aware MCP resource handling."
    ),
  )(process_sans_data)
