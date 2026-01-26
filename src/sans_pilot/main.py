"""MCP server for SANS data analysis."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import secrets
import time
from pathlib import Path
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.dependencies import get_http_request
from fastmcp.utilities.types import Image
from starlette.requests import Request


def _get_api_token() -> str | None:
  """Get the API token from environment variables."""
  return os.environ.get("API_TOKEN")


def _validate_token(token: str) -> bool:
  """Validate the bearer token using timing-safe comparison."""
  expected_token = _get_api_token()
  if not expected_token:
    # No token configured, accept all tokens
    return True
  return secrets.compare_digest(token, expected_token)


# Configure auth provider if token is set
_api_token = _get_api_token()
_auth_verifier = (
  DebugTokenVerifier(
    validate=_validate_token,
    client_id="librechat",
    scopes=["sans:read", "sans:write"],
  )
  if _api_token
  else None
)

mcp = FastMCP("sans-pilot", auth=_auth_verifier)


def _get_upload_dir() -> Path:
  return Path(os.environ.get("UPLOAD_DIR", "/uploads"))


def _get_uploads_dir(user_id: str | None = None) -> Path:
  data_dir = _get_upload_dir()
  if user_id:
    return data_dir / user_id
  return data_dir


def _get_user_id_from_request() -> str | None:
  request: Request = get_http_request()
  return request.headers.get("x-user-id")


def _resolve_uploaded_path(path_or_name: str, user_id: str | None = None) -> Path:
  p = Path(path_or_name)
  if p.is_absolute():
    return p

  uploads_dir = _get_uploads_dir(user_id)

  # Direct relative path within uploads dir
  direct_path = uploads_dir / p
  if direct_path.exists():
    return direct_path

  # Search by filename
  matches = [match for match in uploads_dir.rglob(p.name) if match.is_file()]
  if len(matches) == 1:
    return matches[0]
  if len(matches) > 1:
    raise ValueError(
      f"Ambiguous filename '{p.name}' (found {len(matches)} matches). "
      "Use the full relative path returned by list-uploaded-files."
    )

  raise FileNotFoundError(
    f"Uploaded file '{path_or_name}' not found under {uploads_dir}"
  )


def _templates_dir() -> Path:
  return Path(__file__).parent / "templates"


def _load_template(template_name: str):
  """Load a template module by name."""
  template_path = _templates_dir() / f"{template_name}.py"
  if not template_path.exists():
    raise FileNotFoundError(f"Template not found: {template_name}")

  spec = importlib.util.spec_from_file_location(template_name, template_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Failed to load template: {template_name}")

  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


@mcp.tool(
  name="describe-possibilities",
  description="Describe the capabilities of this SANS data analysis server.",
)
def describe_possibilities() -> str:
  """Describe server capabilities."""
  return (
    "This server can analyze SANS (Small Angle Neutron Scattering) data. "
    "Use list-templates to see available analysis templates, "
    "list-uploaded-files to find data files, "
    "and run-template to execute an analysis."
  )


@mcp.tool(
  name="list-uploaded-files",
  description=(
    "List uploaded data files. "
    "Optional: filter by extensions (e.g. ['csv']), limit results."
  ),
)
def list_uploaded_files(
  extensions: list[str] | None = None,
  limit: int = 50,
) -> list[dict[str, Any]]:
  """List uploaded files, optionally filtered by extension."""
  user_id = _get_user_id_from_request()
  uploads_dir = _get_uploads_dir(user_id)
  extensions_norm = None
  if extensions:
    extensions_norm = {e.lower().lstrip(".") for e in extensions}

  results: list[dict[str, Any]] = []
  for file_path in uploads_dir.rglob("*"):
    if not file_path.is_file():
      continue
    if extensions_norm is not None:
      suffix = file_path.suffix.lower().lstrip(".")
      if suffix not in extensions_norm:
        continue

    stat = file_path.stat()
    results.append(
      {
        "name": file_path.name,
        "relative_path": str(file_path.relative_to(uploads_dir)),
        "bytes": stat.st_size,
      }
    )
    if len(results) >= limit:
      break

  return results


@mcp.tool(
  name="list-templates",
  description="List available analysis templates with their parameters.",
)
def list_templates() -> dict[str, str]:
  """List available templates with descriptions."""
  result = {}
  for path in _templates_dir().glob("*.py"):
    if path.name.startswith("_"):
      continue
    name = path.stem
    try:
      module = _load_template(name)
      result[name] = getattr(module, "TEMPLATE_DESCRIPTION", "No description")
    except Exception:
      result[name] = "Failed to load description"
  return result


def _execute_template(name: str, parameters: dict[str, Any]) -> dict[str, Any]:
  """Execute a template synchronously (runs in thread pool)."""
  module = _load_template(name)
  run_func = getattr(module, "run", None)
  if not callable(run_func):
    raise RuntimeError(f"Template '{name}' has no run() function")
  return cast(dict[str, Any], run_func(**parameters))


@mcp.tool(
  name="run-template",
  description=(
    "Run a SANS analysis template. "
    "Args: name (template id), parameters (dict with input_csv and template-specific options). "
    "Returns fit results and a plot image."
  ),
)
async def run_template(
  name: str,
  parameters: dict[str, Any] | None = None,
) -> list[str | Image]:
  """Run a template and return fit results with plot."""

  parameters = parameters or {}

  # Resolve input file path if provided
  input_csv = parameters.get("input_csv")
  if isinstance(input_csv, str) and input_csv.strip():
    user_id = _get_user_id_from_request()
    parameters["input_csv"] = str(
      _resolve_uploaded_path(input_csv.strip(), user_id=user_id)
    )

  # Create output directory
  runs_dir = Path(os.environ.get("SANS_PILOT_RUNS_DIR", "/tmp/sans-pilot-runs"))
  runs_dir.mkdir(parents=True, exist_ok=True)
  run_id = str(int(time.time() * 1000))
  parameters["output_dir"] = str(runs_dir / name.replace("/", "_") / run_id)

  # Run template in thread pool to avoid blocking the event loop
  template_result = await asyncio.to_thread(_execute_template, name, parameters)

  return [template_result["fit"], Image(path=template_result["artifacts"]["plot"])]


def main() -> None:
  """Start the MCP server."""
  mcp.run()


if __name__ == "__main__":
  main()
