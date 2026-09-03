"""Typed sasmodels construction and configuration services."""

from __future__ import annotations

import contextlib
import io
from typing import Any

from sans_fitter import SANSFitter

from sans_pilot.analyses._fitting_helpers import normalize_value
from sans_pilot.schemas import (
  AtomicModel,
  CompositeModel,
  ModelSpecification,
  ParameterOverride,
  PolydispersitySetting,
)

STRUCTURE_FACTORS: dict[str, str] = {
  "hardsphere": (
    "Hard-sphere Percus-Yevick interactions for excluded-volume repulsion."
  ),
  "hayter_msa": "Hayter-Penfold rescaled MSA for charged-sphere interactions.",
  "squarewell": "Square-well potential for finite-range attractive interactions.",
  "stickyhardsphere": (
    "Baxter sticky-hard-sphere model for very short-range attraction."
  ),
}


def construct_model(fitter: SANSFitter, specification: ModelSpecification) -> None:
  """Construct an atomic/product/composite model without applying links."""
  if isinstance(specification, AtomicModel):
    fitter.set_model(specification.model)
    if specification.structure_factor is not None:
      fitter.set_structure_factor(
        specification.structure_factor,
        radius_effective_mode=specification.radius_effective_mode,
      )
    return

  if isinstance(specification, CompositeModel):
    components: dict[str, str] = {}
    for component in specification.components:
      expression = component.model
      if component.structure_factor is not None:
        expression = f"{expression}@{component.structure_factor}"
      components[component.alias] = expression
    fitter.set_models(
      operation=specification.operation,
      shared=specification.shared_parameters,
      **components,
    )
    return

  raise TypeError(f"Unsupported model specification: {type(specification).__name__}.")


def apply_parameter_overrides(
  fitter: SANSFitter,
  overrides: dict[str, ParameterOverride],
) -> None:
  """Pass parameter settings through to sans-fitter."""
  for name, override in overrides.items():
    fitter.set_param(name, **override.model_dump(exclude_none=True))


def apply_polydispersity(
  fitter: SANSFitter,
  settings: dict[str, PolydispersitySetting],
) -> None:
  """Apply explicitly requested size-distribution settings."""
  if not settings:
    return
  fitter.enable_polydispersity(True)
  for name, setting in settings.items():
    fitter.set_pd_param(name, **setting.model_dump())


def friendly_polydisperse_parameters(fitter: SANSFitter) -> list[str]:
  """Return public component aliases without exposing sasmodels A/B prefixes."""
  components = sorted(
    fitter.get_components(), key=lambda item: len(item[0]), reverse=True
  )
  result: list[str] = []
  for name in fitter.get_polydisperse_parameters():
    friendly = name
    for prefix, alias, _model in components:
      marker = f"{prefix}_"
      if name.startswith(marker):
        friendly = f"{alias}_{name[len(marker) :]}"
        break
    result.append(friendly)
  return result


def resolved_polydispersity_configuration(
  fitter: SANSFitter,
  settings: dict[str, PolydispersitySetting],
) -> dict[str, Any]:
  """Return all applied fixed and varied size-distribution settings."""
  resolved: dict[str, Any] = {}
  for name in settings:
    configuration = fitter.get_pd_param(name)
    resolved[name] = {
      "pd_width": normalize_value(configuration.get("pd")),
      "pd_type": configuration.get("pd_type"),
      "pd_n": normalize_value(configuration.get("pd_n")),
      "pd_nsigma": normalize_value(configuration.get("pd_nsigma")),
      "vary": bool(configuration.get("vary", False)),
      "active": bool(configuration.get("active", False)),
    }
  return resolved


def apply_parameter_links(
  fitter: SANSFitter,
  specification: ModelSpecification,
) -> None:
  """Apply equality links after all writable parameter settings."""
  for follower, target in specification.parameter_links.items():
    fitter.link_params(follower, to=target)


def resolved_model_configuration(
  fitter: SANSFitter,
  specification: ModelSpecification,
) -> dict[str, Any]:
  """Return bounded, user-facing model provenance."""
  if isinstance(specification, AtomicModel):
    expression = specification.model
    if specification.structure_factor is not None:
      expression = f"{expression}@{specification.structure_factor}"
    result: dict[str, Any] = {
      "kind": "atomic",
      "expression": expression,
      "model": specification.model,
      "structure_factor": specification.structure_factor,
      "radius_effective_mode": specification.radius_effective_mode,
    }
  else:
    result = {
      "kind": "composite",
      "expression": specification.operation.join(
        component.model
        + (
          f"@{component.structure_factor}"
          if component.structure_factor is not None
          else ""
        )
        for component in specification.components
      ),
      "operation": specification.operation,
      "components": [
        {
          "alias": component.alias,
          "model": component.model,
          "structure_factor": component.structure_factor,
        }
        for component in specification.components
      ],
      "shared_parameters": list(specification.shared_parameters),
    }
  result["parameter_links"] = dict(fitter.get_links())
  return result


def describe_model(specification: ModelSpecification) -> dict[str, Any]:
  """Construct an exact model and return its strict discovery contract."""
  fitter = SANSFitter()
  with contextlib.redirect_stdout(io.StringIO()):
    construct_model(fitter, specification)
    apply_parameter_links(fitter, specification)
  polydisperse_parameters = friendly_polydisperse_parameters(fitter)
  parameters = normalize_value(fitter.params)
  return {
    "schema_version": "1.0",
    "model": resolved_model_configuration(fitter, specification),
    "parameters": parameters,
    "polydisperse_parameters": polydisperse_parameters,
    "components": [
      {"prefix": prefix, "alias": alias, "model": model}
      for prefix, alias, model in fitter.get_components()
    ],
  }
