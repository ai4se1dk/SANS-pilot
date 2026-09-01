"""Direct typed MCP tools for model-free SANS P(r) analysis."""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from sans_pilot.artifacts import artifact_result, create_run_directory
from sans_pilot.files import get_user_id_from_request
from sans_pilot.inversion import invert_sans_pr_service, scan_sans_dmax_service
from sans_pilot.schemas import InvertSansPrRequest, ScanSansDmaxRequest


async def scan_sans_dmax(request: ScanSansDmaxRequest) -> dict[str, Any]:
  """Scan Dmax to identify stable Rg/I(0), fit-quality, and positivity regions."""
  user_id = get_user_id_from_request()
  result = await asyncio.to_thread(
    scan_sans_dmax_service,
    request,
    user_id=user_id,
    output_dir=create_run_directory("scan-sans-dmax"),
  )
  return artifact_result(result["summary"], result["artifacts"], user_id=user_id)


async def invert_sans_pr(request: InvertSansPrRequest) -> dict[str, Any]:
  """Recover the model-free real-space pair distance distribution P(r)."""
  user_id = get_user_id_from_request()
  result = await asyncio.to_thread(
    invert_sans_pr_service,
    request,
    user_id=user_id,
    output_dir=create_run_directory("invert-sans-pr"),
  )
  return artifact_result(result["summary"], result["artifacts"], user_id=user_id)


def register_inversion_tools(mcp: FastMCP) -> None:
  """Register bounded P(r) discovery and inversion tools."""
  mcp.tool(
    name="scan-sans-dmax",
    description=(
      "Explore a bounded Dmax range before P(r) inversion. Returns Rg, I(0), "
      "data chi-squared, oscillation, positivity, background, and alpha trends "
      "plus a scan plot. Look for stable Rg/I(0) plateaus and physically "
      "acceptable positivity; do not choose Dmax from chi-squared alone."
    ),
  )(scan_sans_dmax)
  mcp.tool(
    name="invert-sans-pr",
    description=(
      "Perform model-free Moore-style indirect Fourier inversion to P(r) at "
      "an explicitly selected Dmax. Supports automatic or fully manual basis "
      "and regularization selection, fixed or fitted background, diagnostic "
      "plots, and optional P(r) CSV export."
    ),
  )(invert_sans_pr)
