"""Custom model fitting analysis for sasmodels."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Literal

from sans_fitter import SANSFitter

from sans_pilot.analyses._data_pipeline import (
  apply_q_range,
  inspect_data,
  prepare_data,
)
from sans_pilot.analyses._fitting_helpers import (
  build_parameter_export,
  filter_actionable_warnings,
  format_fit_result,
  format_posterior_summary,
  serialize_sasview_parameter_values,
)
from sans_pilot.analyses._fitting_workflow import (
  DEFAULT_BAYESIAN_BURN,
  DEFAULT_BAYESIAN_POP,
  DEFAULT_BAYESIAN_SAMPLES,
  DEFAULT_BAYESIAN_THIN,
  configure_fitter,
  run_fit,
  write_posterior_artifacts,
)

ANALYSIS_NAME = "fitting-with-custom-model"
ANALYSIS_DESCRIPTION = (
  "Fit SANS data using a sasmodels model. "
  "input_file accepts CSV, CanSAS XML, or NXcanSAS/HDF5 data. "
  "Required parameters: input_file, model, param_overrides. "
  "Optional data controls: auxiliary_files, ordered data_operations, q_min, q_max. "
  "Optional model controls: structure_factor, structure_factor_params, "
  "radius_effective_mode, and polydispersity. "
  "Set fit_type='optimization' for bumps/lmfit optimization or "
  "fit_type='bayesian' for DREAM posterior sampling. "
  "Bayesian controls: samples, burn, thin, pop, posterior_plots, "
  "posterior_parameters, posterior_predictive_style, and "
  "posterior_predictive_draws. Set include_fit_results_file or "
  "include_posterior_chain only when the user requests raw numerical files. "
  "Returns a compact fit summary, a fit plot, and SasView parameter values; "
  "Bayesian fits also return selected posterior plots."
)


def run(
  *,
  input_file: str | Path,
  output_dir: str | Path,
  model: str,
  param_overrides: dict[str, dict[str, Any]],
  auxiliary_files: dict[str, str | Path] | None = None,
  data_operations: list[dict[str, Any]] | None = None,
  q_min: float | None = None,
  q_max: float | None = None,
  structure_factor: str | None = None,
  structure_factor_params: dict[str, dict[str, Any]] | None = None,
  radius_effective_mode: Literal["unconstrained", "link_radius"] = "unconstrained",
  polydispersity: dict[str, dict[str, Any]] | None = None,
  fit_type: Literal["optimization", "bayesian"] = "optimization",
  engine: Literal["bumps", "lmfit"] = "bumps",
  method: str | None = None,
  samples: int = DEFAULT_BAYESIAN_SAMPLES,
  burn: int = DEFAULT_BAYESIAN_BURN,
  thin: int = DEFAULT_BAYESIAN_THIN,
  pop: int = DEFAULT_BAYESIAN_POP,
  posterior_plots: list[str] | None = None,
  posterior_parameters: list[str] | None = None,
  posterior_predictive_style: Literal["band", "draws", "band+draws"] = "band",
  posterior_predictive_draws: int = 50,
  include_fit_results_file: bool = False,
  include_posterior_chain: bool = False,
  plot_log_scale: bool = True,
) -> dict[str, Any]:
  """Prepare data, configure a model, run a fit, and write result artifacts."""
  input_path = Path(input_file)
  if not input_path.is_file():
    raise FileNotFoundError(f"Input data file not found: {input_path}")

  out_dir = Path(output_dir)
  out_dir.mkdir(parents=True, exist_ok=True)

  prepared = prepare_data(
    input_file=input_path,
    auxiliary_files=auxiliary_files,
    data_operations=data_operations,
  )
  fitter = SANSFitter()

  with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    fitter.set_data(prepared.data)
    apply_q_range(fitter, q_min=q_min, q_max=q_max)
    configure_fitter(
      fitter,
      model=model,
      param_overrides=param_overrides,
      structure_factor=structure_factor,
      structure_factor_params=structure_factor_params,
      radius_effective_mode=radius_effective_mode,
      polydispersity=polydispersity,
    )
    fit_result = run_fit(
      fitter,
      fit_type=fit_type,
      engine=engine,
      method=method,
      samples=samples,
      burn=burn,
      thin=thin,
      pop=pop,
    )

  warning_messages = filter_actionable_warnings(
    [*prepared.warnings, *(str(item.message) for item in captured)]
  )

  parameter_rows = build_parameter_export(
    model=model,
    params=fitter.params,
    fit_result=fit_result,
  )
  parameter_text_path = out_dir / "sasview_parameter_values.txt"
  parameter_text_path.write_text(
    serialize_sasview_parameter_values(parameter_rows),
    encoding="utf-8",
  )

  fit_plot_path = out_dir / "fit_plot.png"
  fitter.plot_results(
    show_residuals=True,
    log_scale=plot_log_scale,
    show=False,
  ).write_image(fit_plot_path)

  fit_results_path = out_dir / "fit_results.csv"
  fitter.save_results(str(fit_results_path))

  artifacts: dict[str, Path] = {
    fit_plot_path.name: fit_plot_path,
    parameter_text_path.name: parameter_text_path,
  }
  if include_fit_results_file:
    artifacts[fit_results_path.name] = fit_results_path

  data_summary = inspect_data(fitter.data, source_path=input_path)
  formatted_result: dict[str, Any] = {
    "model": model,
    **format_fit_result(fit_result),
    "q_range": {
      **data_summary["fit_q_range"],
      "points_fitted": data_summary["points_fitted"],
      "points_total": data_summary["points_total"],
    },
    "data": {
      key: value
      for key, value in data_summary.items()
      if key not in {"fit_q_range", "points_fitted", "points_total"}
    },
    "preprocessing": prepared.preprocessing,
  }
  if structure_factor is not None:
    formatted_result["structure_factor"] = {
      "name": structure_factor,
      "radius_effective_mode": radius_effective_mode,
    }
  if warning_messages:
    formatted_result["warnings"] = warning_messages

  if fit_type == "bayesian":
    posterior = fitter.get_posterior()
    formatted_result["posterior"] = format_posterior_summary(posterior)
    artifacts.update(
      write_posterior_artifacts(
        fitter,
        output_dir=out_dir,
        include_chain=include_posterior_chain,
        plots=posterior_plots if posterior_plots is not None else ["predictive"],
        parameters=posterior_parameters,
        predictive_style=posterior_predictive_style,
        predictive_draws=posterior_predictive_draws,
        log_scale=plot_log_scale,
      )
    )

  return {"fit": formatted_result, "artifacts": artifacts}


if __name__ == "__main__":
  import sys

  if len(sys.argv) < 2:
    raise SystemExit("Usage: python fitting-with-custom-model.py <input_file> [model]")

  print(
    run(
      input_file=sys.argv[1],
      output_dir=Path.cwd() / "fit-output",
      model=sys.argv[2] if len(sys.argv) > 2 else "cylinder",
      param_overrides={
        "radius": {"value": 20, "min": 1, "max": 200, "vary": True},
        "length": {"value": 400, "min": 10, "max": 4000, "vary": True},
        "scale": {"value": 1.0, "min": 0.0, "max": 10, "vary": True},
        "background": {"value": 0.001, "min": 0, "max": 1, "vary": True},
      },
    )
  )
