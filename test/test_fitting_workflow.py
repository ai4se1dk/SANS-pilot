"""Tests for strict fitter workflow helpers."""

from __future__ import annotations

import pytest

from sans_pilot.analyses._fitting_workflow import (
  MAX_BAYESIAN_SAMPLES,
  configure_fitter,
  run_fit,
  write_posterior_artifacts,
)


class FakeFitter:
  def __init__(self):
    self.params = {"radius": {}, "scale": {}}
    self.calls = []

  def set_model(self, model):
    self.calls.append(("model", model))

  def set_structure_factor(self, name, *, radius_effective_mode):
    self.calls.append(("structure_factor", name, radius_effective_mode))
    self.params["volfraction"] = {}

  def set_param(self, name, **config):
    self.calls.append(("parameter", name, config))

  def get_polydisperse_parameters(self):
    return ["radius"]

  def set_pd_param(self, name, **config):
    self.calls.append(("polydispersity", name, config))

  def enable_polydispersity(self, enabled):
    self.calls.append(("polydispersity_enabled", enabled))

  def fit(self, *, engine, method):
    return {"kind": "optimization", "engine": engine, "method": method}

  def fit_bayesian(self, **options):
    return {"kind": "bayesian", **options}


def test_configure_fitter_applies_strict_configuration():
  fitter = FakeFitter()
  configure_fitter(
    fitter,
    model="sphere",
    param_overrides={"radius": {"value": 50, "vary": True}},
    structure_factor="hardsphere",
    structure_factor_params={"volfraction": {"value": 0.2}},
    radius_effective_mode="link_radius",
    polydispersity={"radius": {"pd_width": 0.1}},
  )

  assert ("model", "sphere") in fitter.calls
  assert ("parameter", "radius", {"value": 50, "vary": True}) in fitter.calls
  assert ("parameter", "volfraction", {"value": 0.2}) in fitter.calls
  assert ("polydispersity", "radius", {"pd_width": 0.1}) in fitter.calls


def test_configure_fitter_rejects_unknown_parameter():
  with pytest.raises(ValueError, match="Unknown model parameter"):
    configure_fitter(
      FakeFitter(),
      model="sphere",
      param_overrides={"diameter": {"value": 50}},
      structure_factor=None,
      structure_factor_params=None,
      radius_effective_mode="unconstrained",
      polydispersity=None,
    )


def test_run_fit_uses_optimization_contract():
  result = run_fit(
    FakeFitter(),
    fit_type="optimization",
    engine="lmfit",
    method="leastsq",
    samples=5,
    burn=0,
    thin=1,
    pop=1,
  )
  assert result == {
    "kind": "optimization",
    "engine": "lmfit",
    "method": "leastsq",
  }


def test_run_fit_uses_bounded_bayesian_contract():
  result = run_fit(
    FakeFitter(),
    fit_type="bayesian",
    engine="bumps",
    method=None,
    samples=100,
    burn=10,
    thin=2,
    pop=4,
  )
  assert result == {
    "kind": "bayesian",
    "method": "dream",
    "samples": 100,
    "burn": 10,
    "thin": 2,
    "pop": 4,
  }


def test_run_fit_rejects_expensive_or_wrong_bayesian_configuration():
  with pytest.raises(ValueError, match="samples must be between"):
    run_fit(
      FakeFitter(),
      fit_type="bayesian",
      engine="bumps",
      method=None,
      samples=MAX_BAYESIAN_SAMPLES + 1,
      burn=10,
      thin=1,
      pop=4,
    )

  with pytest.raises(ValueError, match="uses the bumps engine"):
    run_fit(
      FakeFitter(),
      fit_type="bayesian",
      engine="lmfit",
      method=None,
      samples=100,
      burn=10,
      thin=1,
      pop=4,
    )


def test_posterior_chain_is_only_written_when_requested(tmp_path):
  class Posterior:
    labels = ["radius"]

    def save_posterior_csv(self, filename):
      with open(filename, "w", encoding="utf-8") as output:
        output.write("radius\n50\n")

  class Fitter:
    def get_posterior(self):
      return Posterior()

  common = {
    "fitter": Fitter(),
    "output_dir": tmp_path,
    "plots": [],
    "parameters": None,
    "predictive_style": "band",
    "predictive_draws": 5,
    "log_scale": True,
  }

  artifacts = write_posterior_artifacts(include_chain=False, **common)
  assert "posterior_chain.csv" not in artifacts
  assert not (tmp_path / "posterior_chain.csv").exists()

  artifacts = write_posterior_artifacts(include_chain=True, **common)
  assert artifacts["posterior_chain.csv"].is_file()
