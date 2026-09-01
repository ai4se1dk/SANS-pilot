"""Typed MCP entry point for SANS model fitting."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from sans_pilot.artifacts import artifact_result, create_run_directory
from sans_pilot.files import get_user_id_from_request
from sans_pilot.fitting import run_typed_fit
from sans_pilot.schemas import FitSansModelRequest


async def fit_sans_model(request: FitSansModelRequest) -> Any:
  """Fit a typed atomic, interacting, or composite sasmodels model."""
  output_dir = create_run_directory("fit-sans-model")
  user_id = get_user_id_from_request()
  result = await asyncio.to_thread(
    run_typed_fit,
    request,
    user_id=user_id,
    output_dir=output_dir,
  )
  return artifact_result(result["summary"], result["artifacts"], user_id=user_id)


def register_fit_tools(mcp: FastMCP) -> None:
  """Register the strict unified fitting tool."""
  mcp.tool(
    name="fit-sans-model",
    description=(
      "Fit a reduced 1D SANS dataset using an atomic form factor, optional "
      "structure factor, or a composite model. Requires an explicit typed "
      "dataset pipeline, exact model specification, parameter overrides, "
      "and optimization or Bayesian settings. Returns a "
      "bounded scientific summary plus selected artifacts."
    ),
  )(fit_sans_model)
