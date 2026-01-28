"""Analysis loading and execution helpers for the MCP server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast


def get_analyses_dir() -> Path:
  """Get the analyses directory path."""
  return Path(__file__).parent / "analyses"


def load_analysis(analysis_name: str) -> ModuleType:
  """Load an analysis module by name.

  Args:
    analysis_name: Name of the analysis (without .py extension)

  Returns:
    Loaded module

  Raises:
    FileNotFoundError: If analysis module doesn't exist
    RuntimeError: If module cannot be loaded
  """
  analysis_path = get_analyses_dir() / f"{analysis_name}.py"
  if not analysis_path.exists():
    raise FileNotFoundError(f"Analysis not found: {analysis_name}")

  spec = importlib.util.spec_from_file_location(analysis_name, analysis_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Failed to load analysis: {analysis_name}")

  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def execute_analysis(name: str, parameters: dict[str, Any]) -> dict[str, Any]:
  """Execute an analysis synchronously.

  Args:
    name: Analysis name
    parameters: Parameters to pass to the analysis run() function

  Returns:
    Analysis result dictionary

  Raises:
    RuntimeError: If analysis has no run() function
  """
  module = load_analysis(name)
  run_func = getattr(module, "run", None)
  if not callable(run_func):
    raise RuntimeError(f"Analysis '{name}' has no run() function")
  return cast(dict[str, Any], run_func(**parameters))
