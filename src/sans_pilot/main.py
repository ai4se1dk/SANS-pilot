"""MCP server for SANS data analysis."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.utilities.types import File, Image
from sans_fitter import SANSFitter

from sans_pilot.analysis_loader import execute_analysis, get_analyses_dir, load_analysis
from sans_pilot.auth import create_auth_verifier
from sans_pilot.files import (
  get_uploads_dir,
  get_user_id_from_request,
  resolve_uploaded_path,
)

mcp = FastMCP(
  "sans-pilot",
  auth=create_auth_verifier(),
  instructions="""
SANS (Small-Angle Neutron Scattering) data analysis server.

## Workflow
1. `list-uploaded-files` - Find user's CSV data files
2. `list-analyses` - Discover valid analysis names
3. `list-sans-models` - Show available models (cylinder, sphere, ellipsoid, etc.)
4. `get-model-parameters` - Get parameter specs for a model
5. `run-analysis` - Execute fitting with model, param_overrides, and optional structure_factor/polydispersity

## Tool Calling Rule
- Never call `run-analysis` with a guessed `name`
- Always call `list-analyses` first and use an exact key from that response

## Low-Friction First Run
- If user asks to run analysis without specifying a model, do not block for model selection
- Use latest uploaded CSV, choose a valid analysis from `list-analyses`, and run an initial baseline fit
- Ask follow-up questions only when there is no usable file or tool execution fails

## Key Tools
- `list-structure-factors` / `get-structure-factor-parameters` - For concentrated samples with particle interactions
- `get-polydisperse-parameters` / `get-polydispersity-options` - For size distributions

## Fitting Tips
- Set `vary: true` for parameters to optimize (radius, length, scale, background)
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
    "run-analysis (execute an analysis and get fit results + plot)."
  )


@mcp.tool(
  name="list-sans-models",
  description=("List available SANS models which can be used for fitting data."),
)
def list_sans_models():
  from sasmodels import core

  all_models = core.list_models()
  return sorted(all_models)


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
    "Optional: filter by extensions (e.g. ['csv']), limit results. "
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


@mcp.tool(
  name="run-analysis",
  description=(
    "Run a SANS analysis. "
    "Args: name (analysis id from list-analyses), "
    "parameters (dict with input_csv and analysis-specific options like model, engine, param_overrides). "
    "Returns depending on analysis but typically includes fit results and plot artifacts."
  ),
)
async def run_analysis(
  name: str,
  parameters: dict[str, Any] | None = None,
) -> list[str | Image | File]:
  """Run an analysis and return fit results with plot."""

  parameters = parameters or {}

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

  # Resolve input file path if provided
  input_csv = parameters.get("input_csv")
  if isinstance(input_csv, str) and input_csv.strip():
    user_id = get_user_id_from_request()
    parameters["input_csv"] = str(
      resolve_uploaded_path(input_csv.strip(), user_id=user_id)
    )

  # Create output directory
  runs_dir = Path(os.environ.get("SANS_PILOT_RUNS_DIR", "/tmp/sans-pilot-runs"))
  runs_dir.mkdir(parents=True, exist_ok=True)
  run_id = str(int(time.time() * 1000))
  parameters["output_dir"] = str(runs_dir / name.replace("/", "_") / run_id)

  # Run analysis in thread pool to avoid blocking the event loop
  analysis_result = await asyncio.to_thread(execute_analysis, name, parameters)

  response: list[str | Image | File] = []

  fit_output = analysis_result.get("fit")
  if fit_output is not None:
    response.append(str(fit_output))

  artifacts = analysis_result.get("artifacts")
  _append_artifact_to_response(response, artifacts)

  return response


def main() -> None:
  mcp.run()


if __name__ == "__main__":
  main()
