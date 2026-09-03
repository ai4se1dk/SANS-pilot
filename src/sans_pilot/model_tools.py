"""Typed MCP discovery tools for sasmodels configuration."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from sans_fitter import PD_DEFAULTS, PD_DISTRIBUTION_TYPES, get_all_models

from sans_pilot.models import STRUCTURE_FACTORS, describe_model
from sans_pilot.schemas import ModelSpecification


def list_sans_models() -> dict[str, Any]:
  """List exact atomic sasmodels names accepted by model specifications."""
  models = sorted(get_all_models())
  return {
    "schema_version": "1.0",
    "count": len(models),
    "models": models,
    "composition": (
      "Use get-sans-model-parameters with kind='composite' to combine two to "
      "five listed models with + or *."
    ),
  }


def get_sans_model_parameters(model: ModelSpecification) -> dict[str, Any]:
  """Return parameters for the exact atomic, product, or composite model."""
  return describe_model(model)


def list_structure_factors() -> dict[str, Any]:
  """List supported interaction models and composition restrictions."""
  return {
    "schema_version": "1.0",
    "structure_factors": dict(STRUCTURE_FACTORS),
    "atomic_usage": (
      "Set structure_factor on an atomic model and optionally select "
      "radius_effective_mode."
    ),
    "composite_usage": (
      "Set structure_factor on an individual component. A structure factor "
      "cannot be applied to the combined expression."
    ),
  }


def get_polydispersity_options() -> dict[str, Any]:
  """Return distributions, defaults, and scientific parameter meanings."""
  return {
    "schema_version": "1.0",
    "distribution_types": list(PD_DISTRIBUTION_TYPES),
    "defaults": dict(PD_DEFAULTS),
    "fields": {
      "pd_width": "Relative distribution width; 0.1 means 10%.",
      "pd_type": "Distribution shape.",
      "pd_n": "Quadrature points; larger values cost more computation.",
      "pd_nsigma": "Distribution range in standard deviations.",
      "vary": "Whether the optimizer estimates pd_width.",
    },
  }


def register_model_tools(mcp: FastMCP) -> None:
  """Register direct typed model-discovery tools."""
  mcp.tool(
    name="list-sans-models",
    description="List exact atomic sasmodels names accepted for SANS fitting.",
  )(list_sans_models)
  mcp.tool(
    name="get-sans-model-parameters",
    description=(
      "Construct an exact atomic, form-factor@structure-factor, or composite "
      "model and return its parameter names, bounds, polydispersity support, "
      "links, components, and engine restrictions."
    ),
  )(get_sans_model_parameters)
  mcp.tool(
    name="list-structure-factors",
    description="List supported SANS structure factors and where they may be applied.",
  )(list_structure_factors)
  mcp.tool(
    name="get-polydispersity-options",
    description="List supported size-distribution types, defaults, and meanings.",
  )(get_polydispersity_options)
