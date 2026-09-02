"""MCP discovery and generation tools for curated and synthetic SANS data."""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path
from typing import Any, cast

import numpy as np
import plotly.graph_objects as go
from fastmcp import FastMCP
from sans_fitter import SANSFitter, examples
from sasdata.dataloader.data_info import Data1D

from sans_pilot.analyses._fitting_helpers import (
  filter_actionable_warnings,
  normalize_value,
)
from sans_pilot.artifacts import artifact_result, create_run_directory
from sans_pilot.datasets import (
  inspect_data,
  load_data_source,
  log_plot_warnings,
  save_processed_data,
)
from sans_pilot.files import get_user_id_from_request
from sans_pilot.runtime import render_runtime, scientific_runtime
from sans_pilot.schemas import (
  ExampleDataSource,
  SimulateSansDataRequest,
  SimulateSansPairRequest,
)
from sans_pilot.workers import run_cancellable_worker

SCHEMA_VERSION = "1.0"


def _example_record(name: str) -> dict[str, Any]:
  record = examples.get_example(name)
  return {
    "name": record.name,
    "description": record.description,
    "source_file": record.filename,
    "source": record.source,
    "suggested_model": record.model,
    "suggested_parameters": normalize_value(record.params),
    "structure_factor": record.structure_factor,
    "polydispersity": normalize_value(record.polydispersity),
    "known_truth": normalize_value(record.truth),
    "notes": record.notes,
    "tags": list(record.tags),
  }


def list_sans_examples(tag: str | None = None) -> dict[str, Any]:
  """List curated example datasets with scientific routing metadata."""
  names = examples.list_examples(tag=tag)
  records = [_example_record(name) for name in names]
  return {
    "schema_version": SCHEMA_VERSION,
    "tag_filter": tag,
    "count": len(records),
    "examples": records,
  }


def inspect_sans_example(name: str) -> dict[str, Any]:
  """Inspect one curated dataset and its suggested scientific configuration."""
  record = _example_record(name)
  loaded = load_data_source(
    examples_to_source(name),
    user_id=None,
  )
  return {
    "schema_version": SCHEMA_VERSION,
    "analysis": "example_inspection",
    "example": record,
    "data": inspect_data(loaded.data),
    "provenance": loaded.provenance,
  }


def examples_to_source(name: str) -> ExampleDataSource:
  """Build the strict source lazily to keep discovery functions simple."""
  return ExampleDataSource(kind="example", name=name)


def _render_single_simulation(
  request: SimulateSansDataRequest,
  *,
  output_dir: Path,
) -> dict[str, Any]:
  with scientific_runtime(), warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    loaded = load_data_source(request.source, user_id=None)
    fitter = SANSFitter()
    with contextlib.redirect_stdout(io.StringIO()):
      fitter.set_data(loaded.data)
      plot_path = output_dir / "simulated_sans_data.png"
      with render_runtime():
        fitter.plot_results(
          show_residuals=False,
          log_scale=request.plot_log_scale,
          show=False,
        ).write_image(plot_path)
    artifacts: dict[str, Path] = {plot_path.name: plot_path}
    if request.include_csv:
      csv_path = output_dir / "simulated_sans_data.csv"
      save_processed_data(loaded.data, csv_path)
      artifacts[csv_path.name] = csv_path

  return {
    "summary": {
      "schema_version": SCHEMA_VERSION,
      "analysis": "data_simulation",
      "generation": loaded.provenance,
      "data": inspect_data(loaded.data),
      "warnings": filter_actionable_warnings(
        [
          *(str(item.message) for item in captured),
          *log_plot_warnings(loaded.data, log_scale=request.plot_log_scale),
        ]
      ),
      "artifacts": _artifact_metadata(artifacts),
    },
    "artifacts": artifacts,
  }


def _pair_plot(
  sample: Data1D,
  background: Data1D,
  *,
  log_scale: bool,
) -> go.Figure:
  figure = go.Figure()
  for label, data in (("sample", sample), ("background", background)):
    figure.add_trace(
      go.Scatter(
        x=np.asarray(data.x),
        y=np.asarray(data.y),
        error_y={"type": "data", "array": np.asarray(data.dy), "visible": True},
        mode="markers",
        name=label,
      )
    )
  figure.update_layout(
    title="Matched simulated SANS sample and background",
    xaxis_title="Q (Å⁻¹)",
    yaxis_title="I(Q)",
    template="plotly_white",
    height=500,
    width=900,
  )
  if log_scale:
    figure.update_xaxes(type="log")
    figure.update_yaxes(type="log")
  return figure


def _render_simulation_pair(
  request: SimulateSansPairRequest,
  *,
  output_dir: Path,
) -> dict[str, Any]:
  source = request.source
  with scientific_runtime(), warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    sample, background = examples.simulate_pair(
      source.model,
      background_level=request.background_level,
      noise=source.noise,
      seed=source.seed,
      qmin=source.q_min,
      qmax=source.q_max,
      npoints=source.points,
      dq=source.relative_resolution,
      **cast(dict[str, Any], source.parameters),
    )
    plot_path = output_dir / "simulated_sans_pair.png"
    with render_runtime():
      _pair_plot(
        sample,
        background,
        log_scale=request.plot_log_scale,
      ).write_image(plot_path)
    artifacts: dict[str, Path] = {plot_path.name: plot_path}
    if request.include_csv:
      sample_path = output_dir / "simulated_sample.csv"
      background_path = output_dir / "simulated_background.csv"
      save_processed_data(sample, sample_path)
      save_processed_data(background, background_path)
      artifacts[sample_path.name] = sample_path
      artifacts[background_path.name] = background_path

  return {
    "summary": {
      "schema_version": SCHEMA_VERSION,
      "analysis": "matched_data_simulation",
      "generation": {
        **source.model_dump(),
        "background_level": request.background_level,
        "background_seed": source.seed + 1 if source.seed is not None else None,
        "sample_truth": normalize_value(getattr(sample, "truth", {})),
      },
      "sample": inspect_data(sample),
      "background": inspect_data(background),
      "warnings": filter_actionable_warnings(
        [
          *(str(item.message) for item in captured),
          *log_plot_warnings(sample, log_scale=request.plot_log_scale),
          *(
            warning.replace("active point(s)", "active background point(s)")
            for warning in log_plot_warnings(
              background,
              log_scale=request.plot_log_scale,
            )
          ),
        ]
      ),
      "artifacts": _artifact_metadata(artifacts),
    },
    "artifacts": artifacts,
  }


def _artifact_metadata(artifacts: dict[str, Path]) -> list[dict[str, str]]:
  return [
    {
      "name": name,
      "mime_type": "image/png" if path.suffix == ".png" else "text/csv",
    }
    for name, path in artifacts.items()
  ]


def _single_simulation_worker(
  request: SimulateSansDataRequest,
  output_dir: Path,
) -> dict[str, Any]:
  return _render_single_simulation(request, output_dir=output_dir)


def _simulation_pair_worker(
  request: SimulateSansPairRequest,
  output_dir: Path,
) -> dict[str, Any]:
  return _render_simulation_pair(request, output_dir=output_dir)


async def simulate_sans_data(
  request: SimulateSansDataRequest,
) -> Any:
  """Generate one SANS dataset with known ground truth."""
  output_dir = create_run_directory("simulate-sans-data")
  user_id = get_user_id_from_request()
  result = await run_cancellable_worker(
    _single_simulation_worker,
    request,
    output_dir,
    operation_name="simulate-sans-data",
    output_dir=output_dir,
  )
  return artifact_result(result["summary"], result["artifacts"], user_id=user_id)


async def simulate_sans_pair(
  request: SimulateSansPairRequest,
) -> Any:
  """Generate reproducible matched sample/background datasets."""
  output_dir = create_run_directory("simulate-sans-pair")
  user_id = get_user_id_from_request()
  result = await run_cancellable_worker(
    _simulation_pair_worker,
    request,
    output_dir,
    operation_name="simulate-sans-pair",
    output_dir=output_dir,
  )
  return artifact_result(result["summary"], result["artifacts"], user_id=user_id)


def register_example_tools(mcp: FastMCP) -> None:
  """Register curated-example and reproducible-simulation tools."""
  mcp.tool(
    name="list-sans-examples",
    description=(
      "List curated 1D datasets with descriptions, tags, suggested models, "
      "starting parameters, structure factors, polydispersity, caveats, and "
      "known truth only where the data is genuinely simulated."
    ),
  )(list_sans_examples)
  mcp.tool(
    name="inspect-sans-example",
    description=(
      "Inspect one curated SANS example, including live Q/data metadata and "
      "its suggested scientific configuration."
    ),
  )(inspect_sans_example)
  mcp.tool(
    name="simulate-sans-data",
    description=(
      "Generate and plot synthetic 1D SANS data through sans-fitter. Set a seed "
      "when reproducible output is required. CSV export is opt-in."
    ),
  )(simulate_sans_data)
  mcp.tool(
    name="simulate-sans-pair",
    description=(
      "Generate a matched sample/background pair through sans-fitter on an "
      "identical Q grid. Set a seed for reproducibility. CSV exports are opt-in."
    ),
  )(simulate_sans_pair)
