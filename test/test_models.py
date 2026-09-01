"""Tests for model configuration pass-through to sans-fitter."""

from __future__ import annotations

from typing import cast

from sans_fitter import SANSFitter

from sans_pilot import models
from sans_pilot.schemas import (
  AtomicModel,
  CompositeModel,
  FitSansModelRequest,
  ModelComponent,
  ParameterOverride,
  PolydispersitySetting,
)


class FakeFitter:
  def __init__(self):
    self.params = {"radius": {}, "small_sld": {}, "large_sld": {}}
    self.calls = []

  def set_model(self, name):
    self.calls.append(("model", name))

  def set_structure_factor(self, name, *, radius_effective_mode):
    self.calls.append(("structure_factor", name, radius_effective_mode))

  def set_models(self, *, operation, shared, **components):
    self.calls.append(("models", operation, shared, components))

  def set_param(self, name, **configuration):
    self.calls.append(("parameter", name, configuration))

  def get_polydisperse_parameters(self):
    return ["radius"]

  def get_components(self):
    return []

  def enable_polydispersity(self, enabled):
    self.calls.append(("pd_enabled", enabled))

  def set_pd_param(self, name, **configuration):
    self.calls.append(("pd", name, configuration))

  def get_pd_param(self, name):
    return {
      "pd": 0.1,
      "pd_type": "gaussian",
      "pd_n": 15,
      "pd_nsigma": 3,
      "vary": False,
      "active": True,
    }

  def link_params(self, follower, *, to):
    self.calls.append(("link", follower, to))


def test_constructs_models_by_calling_sans_fitter_api():
  atomic = FakeFitter()
  models.construct_model(
    cast(SANSFitter, atomic),
    AtomicModel(
      kind="atomic",
      model="sphere",
      structure_factor="hardsphere",
      radius_effective_mode="link_radius",
    ),
  )
  assert atomic.calls == [
    ("model", "sphere"),
    ("structure_factor", "hardsphere", "link_radius"),
  ]

  composite = FakeFitter()
  models.construct_model(
    cast(SANSFitter, composite),
    CompositeModel(
      kind="composite",
      operation="+",
      components=[
        ModelComponent(alias="small", model="sphere"),
        ModelComponent(alias="long", model="cylinder", structure_factor="hardsphere"),
      ],
      shared_parameters=["sld"],
    ),
  )
  assert composite.calls == [
    (
      "models",
      "+",
      ["sld"],
      {"small": "sphere", "long": "cylinder@hardsphere"},
    )
  ]


def test_parameter_and_polydispersity_settings_are_passed_through():
  fitter = FakeFitter()
  models.apply_parameter_overrides(
    cast(SANSFitter, fitter),
    {"dependency_parameter": ParameterOverride(value=10, vary=True)},
  )
  setting = PolydispersitySetting(pd_width=0.1, pd_n=15)
  models.apply_polydispersity(cast(SANSFitter, fitter), {"radius": setting})

  assert fitter.calls[0] == (
    "parameter",
    "dependency_parameter",
    {"value": 10.0, "vary": True},
  )
  assert fitter.calls[1] == ("pd_enabled", True)
  assert fitter.calls[2][0:2] == ("pd", "radius")


def test_fit_schema_does_not_validate_dependency_method_combinations():
  request = FitSansModelRequest.model_validate(
    {
      "pipeline": {"primary": {"kind": "simulation", "model": "sphere", "seed": 42}},
      "model": {
        "kind": "atomic",
        "model": "sphere",
        "parameter_links": {"sld_solvent": "sld"},
      },
      "parameters": {"sld_solvent": {"value": 6.4}},
      "fit": {"mode": "optimization", "engine": "lmfit", "method": "leastsq"},
    }
  )

  assert request.fit.method == "leastsq"  # type: ignore[union-attr]
