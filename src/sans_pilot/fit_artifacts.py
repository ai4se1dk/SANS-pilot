"""Bounded result-file generation for SANS fits."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sans_pilot.runtime import render_runtime
from sans_pilot.schemas import FitArtifactOptions


def _artifact_parameter_name(parameter: str) -> str:
  """Convert a posterior parameter label into a safe artifact name."""
  cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", parameter).strip("._")
  return cleaned or "parameter"


def write_posterior_artifacts(
  fitter: Any,
  *,
  output_dir: Path,
  options: FitArtifactOptions,
) -> dict[str, Path]:
  """Write only the explicitly selected posterior artifacts."""
  posterior = fitter.get_posterior()
  if options.posterior_parameters:
    for parameter in options.posterior_parameters:
      posterior.index_of(parameter)

  artifacts: dict[str, Path] = {}
  if options.include_posterior_chain:
    chain_path = output_dir / "posterior_chain.csv"
    posterior.save_posterior_csv(str(chain_path))
    artifacts[chain_path.name] = chain_path

  plot_builders: dict[str, Any] = {
    "pairs": lambda: fitter.plot_posterior_pairs(
      params=options.posterior_parameters,
      show=False,
    ),
    "predictive": lambda: fitter.plot_posterior_predictive(
      style=options.posterior_predictive_style,
      n_draws=options.posterior_predictive_draws,
      log_scale=options.plot_log_scale,
      show=False,
    ),
    "correlations": lambda: fitter.plot_param_correlations(show=False),
    "trace": lambda: fitter.plot_trace(
      params=options.posterior_parameters,
      show=False,
    ),
  }
  file_names = {
    "pairs": "posterior_pairs.png",
    "predictive": "posterior_predictive.png",
    "correlations": "posterior_correlations.png",
    "trace": "posterior_trace.png",
  }

  for plot_name in options.posterior_plots:
    if plot_name == "distribution":
      parameters = options.posterior_parameters or posterior.labels[:1]
      for parameter in parameters:
        figure = fitter.plot_param_distribution(parameter, show=False)
        path = output_dir / (
          f"posterior_distribution_{_artifact_parameter_name(parameter)}.png"
        )
        with render_runtime():
          figure.write_image(path)
        artifacts[path.name] = path
      continue

    figure = plot_builders[plot_name]()
    path = output_dir / file_names[plot_name]
    with render_runtime():
      figure.write_image(path)
    artifacts[path.name] = path

  return artifacts
