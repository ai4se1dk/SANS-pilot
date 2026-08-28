"""MCP server for SANS data analysis."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
import warnings
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.types import File, Image
from sans_fitter import SANSFitter, data_ops, get_all_models

from sans_pilot.analyses._data_pipeline import inspect_data
from sans_pilot.analysis_loader import execute_analysis, get_analyses_dir, load_analysis
from sans_pilot.auth import create_auth_verifier
from sans_pilot.files import (
  get_uploads_dir,
  get_user_id_from_request,
  resolve_uploaded_path,
)
from sans_pilot.sld import calculate_neutron_sld

mcp = FastMCP(
  "sans-pilot",
  auth=create_auth_verifier(),
  instructions="""
SANS (Small-Angle Neutron Scattering) data analysis server.

## Workflow
1. `list-uploaded-files` - Find the user's SANS data files
2. `inspect-sans-data` - Inspect Q range, uncertainties, resolution, and validity
3. `plot-sans-data` - Plot measured data without selecting or fitting a model
4. `list-analyses` - Discover valid fitting analysis names and parameters
5. `list-sans-models` - Show available models (cylinder, sphere, ellipsoid, etc.)
6. `get-model-parameters` - Get parameter specs for a model
7. `run-analysis` - Run optimization or Bayesian fitting, with optional preprocessing

## Tool Calling Rule
- If the user explicitly asks to plot, visualize, or inspect data without fitting, call `plot-sans-data`; do not call model-discovery tools or `run-analysis`
- Never call `run-analysis` with a guessed `name`
- Always call `list-analyses` first and use an exact key from that response

## Low-Friction First Run
- If the user asks for a fit or analysis without specifying a model, do not block for model selection
- Use the latest uploaded SANS data file, inspect it, choose a valid analysis from `list-analyses`, and run an initial baseline fit
- An explicit plot-only or no-fit request always overrides the baseline-fit workflow
- Ask follow-up questions only when there is no usable file or tool execution fails

## Key Tools
- `list-structure-factors` / `get-structure-factor-parameters` - For concentrated samples with particle interactions
- `get-polydisperse-parameters` / `get-polydispersity-options` - For size distributions
- `data_operations` in `run-analysis` - For background subtraction, scaling, and transmission correction

## Fitting Tips
- Set `vary: true` for parameters to optimize (radius, length, scale, background)
- Use `q_min` and `q_max` to exclude unreliable low- or high-Q regions
- dQ resolution is read automatically when present in the input data
- Use `fit_type: "bayesian"` only when posterior uncertainty analysis is requested
""",
)


_IMAGE_EXTENSIONS = {".png"}


def _append_artifact_to_response(
  response: list[str | Image | File],
  artifact: Any,
) -> None:
  """Append artifact outputs based on current analysis contract."""
  if artifact is None:
    return

  if not isinstance(artifact, dict):
    return

  for value in artifact.values():
    if not isinstance(value, (str, Path)):
      continue

    artifact_path = Path(value)
    suffix = artifact_path.suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
      response.append(Image(path=str(artifact_path)))
      continue
    response.append(File(path=str(artifact_path), name=artifact_path.name))


@mcp.tool(
  name="describe-possibilities",
  description="Describe the capabilities of this SANS data analysis server.",
)
def describe_possibilities() -> str:
  """Describe server capabilities."""
  return (
    "This server can analyze SANS (Small Angle Neutron Scattering) data. "
    "Available tools: "
    "list-sans-models (see available models), "
    "get-model-parameters (get parameter specs for a model), "
    "list-structure-factors (see available structure factors for inter-particle interactions), "
    "get-structure-factor-parameters (get params for form_factor@structure_factor product model), "
    "get-polydisperse-parameters (see which params support polydispersity), "
    "get-polydispersity-options (get PD distribution types and defaults), "
    "list-analyses (see available analysis types), "
    "list-uploaded-files (find data files), "
    "inspect-sans-data (inspect Q range, uncertainties, and resolution), "
    "plot-sans-data (plot measured data without fitting a model), "
    "run-analysis (execute optimization or Bayesian fitting with optional preprocessing), "
    "calculate-sld (compute neutron SLD for a molecular formula and density)."
  )


@mcp.tool(
  name="list-sans-models",
  description=("List available SANS models which can be used for fitting data."),
)
def list_sans_models():
  return get_all_models()


@mcp.tool(
  name="get-model-parameters",
  description=(
    "Get parameters for a SANS model. "
    "Returns dict of parameter names with their default value, min, max, and vary flag."
  ),
)
def get_model_parameters(model_name: str):
  fitter = SANSFitter()
  fitter.set_model(model_name)

  return fitter.params


@mcp.tool(
  name="list-structure-factors",
  description=(
    "List available structure factors for modeling inter-particle interactions. "
    "Structure factors are essential for concentrated systems where particle interactions affect scattering."
  ),
)
def list_structure_factors() -> dict[str, str]:
  """List supported structure factors with descriptions."""
  return {
    "hardsphere": "Hard sphere structure factor (Percus-Yevick closure) - for non-interacting hard spheres",
    "hayter_msa": "Hayter-Penfold rescaled MSA - for charged spheres with Coulombic interactions",
    "squarewell": "Square well potential - for particles with short-range attraction",
    "stickyhardsphere": "Sticky hard sphere (Baxter model) - for particles with very short-range attraction",
  }


@mcp.tool(
  name="get-structure-factor-parameters",
  description=(
    "Get parameters for a form_factor@structure_factor product model. "
    "Returns combined parameters from both form factor and structure factor."
  ),
)
def get_structure_factor_parameters(
  form_factor: str,
  structure_factor: str,
) -> dict[str, Any]:
  """Get parameters for a product model (form_factor@structure_factor)."""
  fitter = SANSFitter()
  fitter.set_model(form_factor)
  fitter.set_structure_factor(structure_factor)
  return fitter.params


@mcp.tool(
  name="get-polydisperse-parameters",
  description=(
    "Get parameters that support polydispersity for a SANS model. "
    "Returns list of parameter names that can have size distributions applied."
  ),
)
def get_polydisperse_parameters(model_name: str) -> dict[str, Any]:
  """Get polydisperse parameters for a model."""
  fitter = SANSFitter()
  fitter.set_model(model_name)

  return {
    "supports_polydispersity": fitter.supports_polydispersity(),
    "polydisperse_parameters": fitter.get_polydisperse_parameters(),
  }


@mcp.tool(
  name="get-polydispersity-options",
  description=(
    "Get available polydispersity distribution types and default values. "
    "Use this to understand PD configuration options before running an analysis."
  ),
)
def get_polydispersity_options() -> dict[str, Any]:
  """Get polydispersity distribution types and defaults."""
  from sans_fitter import PD_DEFAULTS, PD_DISTRIBUTION_TYPES

  return {
    "distribution_types": PD_DISTRIBUTION_TYPES,
    "defaults": PD_DEFAULTS,
    "description": {
      "pd_width": "Relative width of distribution (0.1 = 10% polydispersity)",
      "pd_type": "Distribution shape (gaussian, lognormal, schulz, rectangle, boltzmann)",
      "pd_n": "Number of quadrature points (higher = more accurate, slower)",
      "pd_nsigma": "Number of standard deviations to include",
      "vary": "Whether to fit the pd_width during optimization",
    },
  }


@mcp.tool(
  name="list-uploaded-files",
  description=(
    "List uploaded data files. Show original_name for user clarity. "
    "Optional: filter by extensions (e.g. ['csv', 'xml', 'h5']), limit results. "
    "Returns list of dicts with original_name, name, bytes size and created_time."
  ),
)
def list_uploaded_files(
  extensions: list[str] | None = None,
  limit: int = 50,
) -> list[dict[str, Any]]:
  """List uploaded files, optionally filtered by extension."""
  user_id = get_user_id_from_request()
  uploads_dir = get_uploads_dir(user_id)
  extensions_norm = None
  if extensions:
    extensions_norm = {e.lower().lstrip(".") for e in extensions}

  results: list[dict[str, Any]] = []
  candidates: list[tuple[float, Path]] = []
  for file_path in uploads_dir.rglob("*"):
    if not file_path.is_file():
      continue
    if extensions_norm is not None:
      suffix = file_path.suffix.lower().lstrip(".")
      if suffix not in extensions_norm:
        continue

    stat = file_path.stat()
    candidates.append((stat.st_ctime, file_path))

  for _, file_path in sorted(candidates, key=lambda item: item[0], reverse=True):
    stat = file_path.stat()
    name = file_path.name
    original_name = name
    if "__" in name:
      _, original_name = name.split("__", 1)
    results.append(
      {
        "original_name": original_name,
        "name": name,
        "bytes": stat.st_size,
        "created_time": stat.st_ctime,
      }
    )
    if len(results) >= limit:
      break

  return results


@mcp.tool(
  name="inspect-sans-data",
  description=(
    "Inspect an uploaded SANS data file without fitting it. "
    "Returns file format, point count, full and active Q ranges, availability "
    "of intensity uncertainties (dI) and Q resolution (dQ), and the number "
    "of masked or invalid points. Accepts CSV, CanSAS XML, and NXcanSAS/HDF5."
  ),
)
def inspect_sans_data(input_file: str) -> dict[str, Any]:
  """Load an uploaded dataset and return bounded metadata about it."""
  if not input_file.strip():
    raise ValueError("input_file must name an uploaded SANS data file.")
  user_id = get_user_id_from_request()
  input_path = resolve_uploaded_path(input_file.strip(), user_id=user_id)

  with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    data = data_ops.load(str(input_path))

  result = inspect_data(data, source_path=input_path)
  warning_messages = list(dict.fromkeys(str(item.message) for item in captured))
  if warning_messages:
    result["warnings"] = warning_messages
  return result


@mcp.tool(
  name="list-analyses",
  description="List available analysis types with their parameters.",
)
def list_analyses() -> dict[str, str]:
  """List available analyses with descriptions."""
  result = {}
  for path in get_analyses_dir().glob("*.py"):
    if path.name.startswith("_"):
      continue
    name = path.stem
    try:
      module = load_analysis(name)
      result[name] = getattr(module, "ANALYSIS_DESCRIPTION", "No description")
    except Exception:
      result[name] = "Failed to load description"
  return result


def _safe_run_filename_component(value: str) -> str:
  """Return a filesystem-safe component for an auxiliary-file alias."""
  result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
  return result or "input"


def _copy_run_input(source: Path, destination: Path) -> Path:
  """Copy a resolved upload into an isolated analysis run directory."""
  if not source.is_file():
    raise FileNotFoundError(f"Input data file not found: {source}")
  destination.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(source, destination)
  return destination


def _create_run_directory(operation_name: str) -> Path:
  """Create an isolated output directory for one MCP operation."""
  runs_dir = Path(os.environ.get("SANS_PILOT_RUNS_DIR", "/tmp/sans-pilot-runs"))
  out_dir = runs_dir / _safe_run_filename_component(operation_name) / uuid.uuid4().hex
  out_dir.mkdir(parents=True, exist_ok=True)
  return out_dir


def _render_data_only_plot(
  *,
  input_path: Path,
  output_path: Path,
  log_scale: bool,
) -> dict[str, Any]:
  """Render measured SANS data without configuring or fitting a model."""
  with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    data = data_ops.load(str(input_path))
    fitter = SANSFitter()
    fitter.set_data(data)
    figure = fitter.plot_results(
      show_residuals=False,
      log_scale=log_scale,
      show=False,
    )
    figure.update_layout(height=500, width=900)
    figure.write_image(output_path)

  result = inspect_data(data, source_path=input_path)
  result["plot"] = {
    "type": "data_only",
    "log_scale": log_scale,
    "fit_performed": False,
  }
  warning_messages = list(dict.fromkeys(str(item.message) for item in captured))
  if warning_messages:
    result["warnings"] = warning_messages
  return result


@mcp.tool(
  name="plot-sans-data",
  description=(
    "Plot an uploaded SANS dataset without selecting a model or performing a fit. "
    "Returns measured intensity with available dI and dQ error bars, a compact "
    "data summary, and a PNG plot with no fitted curve or residuals. Accepts "
    "CSV, CanSAS XML, and NXcanSAS/HDF5. Use log_scale=false for linear axes."
  ),
)
async def plot_sans_data(
  input_file: str,
  log_scale: bool = True,
) -> list[str | Image]:
  """Plot a user-scoped uploaded dataset without fitting it."""
  if not isinstance(input_file, str) or not input_file.strip():
    raise ValueError("input_file must name an uploaded SANS data file.")
  if not isinstance(log_scale, bool):
    raise TypeError("log_scale must be true or false.")

  user_id = get_user_id_from_request()
  resolved_input = resolve_uploaded_path(input_file.strip(), user_id=user_id)
  out_dir = _create_run_directory("plot-sans-data")
  copied_input = _copy_run_input(resolved_input, out_dir / resolved_input.name)
  plot_path = out_dir / "sans_data_plot.png"

  result = await asyncio.to_thread(
    _render_data_only_plot,
    input_path=copied_input,
    output_path=plot_path,
    log_scale=log_scale,
  )
  return [
    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
    Image(path=str(plot_path)),
  ]


@mcp.tool(
  name="run-analysis",
  description=(
    "Run a SANS analysis. "
    "Args: name (analysis id from list-analyses), "
    "parameters (dict with input_file, model, param_overrides, and optional "
    "Q range, preprocessing, structure-factor, polydispersity, or Bayesian settings). "
    "Returns a compact JSON summary and downloadable result artifacts."
  ),
)
async def run_analysis(
  name: str,
  parameters: dict[str, Any] | None = None,
) -> list[str | Image | File]:
  """Run an analysis and return fit results with plot."""

  parameters = dict(parameters or {})

  available_analyses = sorted(
    path.stem
    for path in get_analyses_dir().glob("*.py")
    if not path.name.startswith("_")
  )
  if name not in available_analyses:
    available = ", ".join(available_analyses) if available_analyses else "<none>"
    raise ValueError(
      f"Invalid analysis name '{name}'. Call list-analyses first and use an exact name. "
      f"Available analyses: {available}"
    )

  input_file = parameters.get("input_file")
  if not isinstance(input_file, str) or not input_file.strip():
    raise ValueError("parameters.input_file must name an uploaded SANS data file.")

  auxiliary_files = parameters.get("auxiliary_files") or {}
  if not isinstance(auxiliary_files, dict):
    raise TypeError("parameters.auxiliary_files must be an alias-to-filename object.")

  user_id = get_user_id_from_request()
  resolved_input = resolve_uploaded_path(input_file.strip(), user_id=user_id)
  resolved_auxiliary: dict[str, Path] = {}
  for alias, file_name in auxiliary_files.items():
    if not isinstance(alias, str) or not alias.strip():
      raise TypeError("Every auxiliary file alias must be a non-empty string.")
    if not isinstance(file_name, str) or not file_name.strip():
      raise TypeError(f"Auxiliary file '{alias}' must name an uploaded file.")
    if alias in resolved_auxiliary:
      raise ValueError(f"Duplicate auxiliary file alias: '{alias}'.")
    resolved_auxiliary[alias] = resolve_uploaded_path(
      file_name.strip(),
      user_id=user_id,
    )

  # Create an isolated output directory for this run.
  out_dir = _create_run_directory(name)
  parameters["output_dir"] = str(out_dir)

  # Copy every input into the run directory so concurrent analyses are isolated.
  copied_input = _copy_run_input(resolved_input, out_dir / resolved_input.name)
  parameters["input_file"] = str(copied_input)

  copied_auxiliary: dict[str, str] = {}
  for index, (alias, source) in enumerate(resolved_auxiliary.items(), start=1):
    destination = out_dir / (
      f"aux_{index:02d}_{_safe_run_filename_component(alias)}__{source.name}"
    )
    copied_auxiliary[alias] = str(_copy_run_input(source, destination))
  if copied_auxiliary:
    parameters["auxiliary_files"] = copied_auxiliary
  else:
    parameters.pop("auxiliary_files", None)

  # Run analysis in thread pool to avoid blocking the event loop
  analysis_result = await asyncio.to_thread(execute_analysis, name, parameters)

  response: list[str | Image | File] = []

  fit_output = analysis_result.get("fit")
  if fit_output is not None:
    response.append(
      json.dumps(fit_output, ensure_ascii=False, indent=2, sort_keys=True)
    )

  artifacts = analysis_result.get("artifacts")
  _append_artifact_to_response(response, artifacts)

  return response


@mcp.tool(
  name="calculate-sld",
  description=(
    "Calculate the Neutron Scattering Length Density (SLD) for a given "
    "molecular formula and mass density. SLD values are essential for "
    "SANS experiment planning — they determine contrast between sample "
    "components and solvent. Uses the same algorithm as SasView's SLD calculator."
  ),
)
def calculate_sld(
  molecular_formula: str,
  mass_density: float | None = None,
  neutron_wavelength: float = 6.0,
) -> dict:
  return calculate_neutron_sld(molecular_formula, mass_density, neutron_wavelength)


def main() -> None:
  mcp.run()


if __name__ == "__main__":
  main()
