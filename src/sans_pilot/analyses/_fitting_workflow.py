"""Fitter configuration and execution helpers for SANS analyses."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

_PARAMETER_FIELDS = {"value", "min", "max", "vary"}
_PD_FIELDS = {"pd_width", "pd_type", "pd_n", "pd_nsigma", "vary"}
_POSTERIOR_PLOTS = {"pairs", "distribution", "predictive", "correlations", "trace"}

DEFAULT_BAYESIAN_SAMPLES = 5_000
DEFAULT_BAYESIAN_BURN = 200
DEFAULT_BAYESIAN_THIN = 1
DEFAULT_BAYESIAN_POP = 10
MAX_BAYESIAN_SAMPLES = 50_000
MAX_BAYESIAN_BURN = 5_000
MAX_BAYESIAN_THIN = 100
MAX_BAYESIAN_POP = 50
MAX_POSTERIOR_PREDICTIVE_DRAWS = 200


def _apply_parameter_overrides(
  fitter: Any,
  overrides: dict[str, dict[str, Any]],
  *,
  kind: str,
) -> None:
  """Apply strict parameter overrides through the public fitter API."""
  for name, config in overrides.items():
    if name not in fitter.params:
      raise ValueError(f"Unknown {kind} parameter '{name}'.")
    if not isinstance(config, dict):
      raise TypeError(f"Configuration for {kind} parameter '{name}' must be an object.")
    unknown = set(config) - _PARAMETER_FIELDS
    if unknown:
      fields = ", ".join(sorted(unknown))
      raise ValueError(f"Unknown fields for {kind} parameter '{name}': {fields}.")
    fitter.set_param(name, **config)


def configure_fitter(
  fitter: Any,
  *,
  model: str,
  param_overrides: dict[str, dict[str, Any]],
  structure_factor: str | None,
  structure_factor_params: dict[str, dict[str, Any]] | None,
  radius_effective_mode: Literal["unconstrained", "link_radius"],
  polydispersity: dict[str, dict[str, Any]] | None,
) -> None:
  """Configure model, structure factor, parameters, and polydispersity."""
  fitter.set_model(model)

  if structure_factor is not None:
    fitter.set_structure_factor(
      structure_factor,
      radius_effective_mode=radius_effective_mode,
    )
    _apply_parameter_overrides(
      fitter,
      structure_factor_params or {},
      kind="structure-factor",
    )
  elif structure_factor_params:
    raise ValueError("structure_factor_params requires structure_factor.")

  _apply_parameter_overrides(fitter, param_overrides, kind="model")

  if polydispersity is None:
    return

  supported = set(fitter.get_polydisperse_parameters())
  for name, config in polydispersity.items():
    if name not in supported:
      available = ", ".join(sorted(supported)) or "<none>"
      raise ValueError(
        f"Parameter '{name}' does not support polydispersity. Available: {available}."
      )
    if not isinstance(config, dict):
      raise TypeError(f"Polydispersity configuration for '{name}' must be an object.")
    unknown = set(config) - _PD_FIELDS
    if unknown:
      fields = ", ".join(sorted(unknown))
      raise ValueError(f"Unknown polydispersity fields for '{name}': {fields}.")
    fitter.set_pd_param(name, **config)

  fitter.enable_polydispersity(True)


def _bounded_integer(name: str, value: int, *, minimum: int, maximum: int) -> int:
  """Validate a bounded integer option without accepting booleans."""
  if isinstance(value, bool) or not isinstance(value, int):
    raise TypeError(f"{name} must be an integer.")
  if not minimum <= value <= maximum:
    raise ValueError(f"{name} must be between {minimum} and {maximum}.")
  return value


def run_fit(
  fitter: Any,
  *,
  fit_type: Literal["optimization", "bayesian"],
  engine: Literal["bumps", "lmfit"],
  method: str | None,
  samples: int,
  burn: int,
  thin: int,
  pop: int,
) -> dict[str, Any]:
  """Run an optimization or bounded Bayesian fitting workflow."""
  if fit_type == "optimization":
    return fitter.fit(engine=engine, method=method)
  if fit_type != "bayesian":
    raise ValueError("fit_type must be 'optimization' or 'bayesian'.")
  if engine != "bumps":
    raise ValueError("Bayesian fitting uses the bumps engine.")
  if method not in (None, "dream"):
    raise ValueError("Bayesian fitting method must be 'dream'.")

  samples = _bounded_integer(
    "samples", samples, minimum=2, maximum=MAX_BAYESIAN_SAMPLES
  )
  burn = _bounded_integer("burn", burn, minimum=0, maximum=MAX_BAYESIAN_BURN)
  thin = _bounded_integer("thin", thin, minimum=1, maximum=MAX_BAYESIAN_THIN)
  pop = _bounded_integer("pop", pop, minimum=1, maximum=MAX_BAYESIAN_POP)
  return fitter.fit_bayesian(
    method="dream",
    samples=samples,
    burn=burn,
    thin=thin,
    pop=pop,
  )


def _artifact_parameter_name(parameter: str) -> str:
  """Convert a posterior parameter label into a safe artifact name."""
  cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", parameter).strip("._")
  return cleaned or "parameter"


def write_posterior_artifacts(
  fitter: Any,
  *,
  output_dir: Path,
  include_chain: bool,
  plots: list[str],
  parameters: list[str] | None,
  predictive_style: Literal["band", "draws", "band+draws"],
  predictive_draws: int,
  log_scale: bool,
) -> dict[str, Path]:
  """Write selected Bayesian chain and plot artifacts."""
  unknown = set(plots) - _POSTERIOR_PLOTS
  if unknown:
    available = ", ".join(sorted(_POSTERIOR_PLOTS))
    invalid = ", ".join(sorted(unknown))
    raise ValueError(f"Unknown posterior plots: {invalid}. Available: {available}.")

  posterior = fitter.get_posterior()
  if parameters:
    for parameter in parameters:
      posterior.index_of(parameter)

  artifacts: dict[str, Path] = {}
  if include_chain:
    chain_path = output_dir / "posterior_chain.csv"
    posterior.save_posterior_csv(str(chain_path))
    artifacts[chain_path.name] = chain_path

  plot_builders: dict[str, Any] = {
    "pairs": lambda: fitter.plot_posterior_pairs(params=parameters, show=False),
    "predictive": lambda: fitter.plot_posterior_predictive(
      style=predictive_style,
      n_draws=_bounded_integer(
        "posterior_predictive_draws",
        predictive_draws,
        minimum=1,
        maximum=MAX_POSTERIOR_PREDICTIVE_DRAWS,
      ),
      log_scale=log_scale,
      show=False,
    ),
    "correlations": lambda: fitter.plot_param_correlations(show=False),
    "trace": lambda: fitter.plot_trace(params=parameters, show=False),
  }
  file_names = {
    "pairs": "posterior_pairs.png",
    "predictive": "posterior_predictive.png",
    "correlations": "posterior_correlations.png",
    "trace": "posterior_trace.png",
  }

  for plot_name in plots:
    if plot_name == "distribution":
      distribution_parameters = parameters or posterior.labels[:1]
      for parameter in distribution_parameters:
        figure = fitter.plot_param_distribution(parameter, show=False)
        path = output_dir / (
          f"posterior_distribution_{_artifact_parameter_name(parameter)}.png"
        )
        figure.write_image(path)
        artifacts[path.name] = path
      continue

    figure = plot_builders[plot_name]()
    path = output_dir / file_names[plot_name]
    figure.write_image(path)
    artifacts[path.name] = path

  return artifacts
