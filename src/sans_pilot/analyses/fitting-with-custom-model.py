"""Custom model fitting analysis for sasmodels."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from sans_fitter import SANSFitter

ANALYSIS_NAME = "fitting-with-custom-model"
ANALYSIS_DESCRIPTION = (
  "Fit SANS data using a specified model from sasmodels. "
  "Use list-sans-models to see available models, "
  "get-model-parameters to get parameter specs, "
  "get-polydisperse-parameters to see which params support polydispersity. "
  "Parameters: "
  "input_csv (str, required), "
  "model (str, required), "
  "param_overrides (dict, required) - model parameters with value/min/max/vary (set vary=true for params to fit), "
  "polydispersity (dict, optional) - PD config per param with pd_width/pd_type/pd_n/pd_nsigma/vary, "
  "engine (bumps|lmfit, default: bumps), "
  "method (str, default: amoeba), "
  "plot_log_scale (bool, default: True)."
)


def run(
  *,
  input_csv: str | Path,
  output_dir: str | Path,
  model: str,
  param_overrides: dict[str, dict[str, Any]],
  polydispersity: dict[str, dict[str, Any]] | None = None,
  engine: Literal["bumps", "lmfit"] = "bumps",
  method: str | None = "amoeba",
  plot_log_scale: bool = True,
) -> dict[str, Any]:
  """Fit SANS data using a specified sasmodels model.

  Args:
    input_csv: Path to the CSV data file.
    output_dir: Directory for output artifacts.
    model: Name of the SANS model to use.
    param_overrides: Model parameters (value/min/max/vary). Set vary=true for params to fit.
    polydispersity: PD configuration per parameter. Keys are param names, values are dicts
      with pd_width, pd_type, pd_n, pd_nsigma, vary. Example:
      {"radius": {"pd_width": 0.1, "pd_type": "gaussian", "vary": False}}
    engine: Fitting engine ('bumps' or 'lmfit').
    method: Optimization method.
    plot_log_scale: Use log scale for plot.

  Returns:
    Dict with fit results, and artifacts.
  """

  input_path = Path(input_csv)

  # Ensure data file exists
  if not input_path.is_file():
    raise FileNotFoundError(f"Input data file not found: {input_path}")

  # Create output directory if it doesn't exist
  out_dir = Path(output_dir)
  out_dir.mkdir(parents=True, exist_ok=True)

  # Initialize fitter
  fitter = SANSFitter()

  fitter.load_data(str(input_path))

  # Set model
  fitter.set_model(model)

  # Apply parameter overrides
  # Keys that SANSFitter.set_param() accepts
  allowed_keys = {"value", "min", "max", "vary"}
  for param_name, overrides in param_overrides.items():
    if param_name in fitter.params:
      # Filter out keys not supported by set_param
      filtered = {k: v for k, v in overrides.items() if k in allowed_keys}
      if filtered:
        fitter.set_param(param_name, **filtered)
    else:
      print(f"Warning: param '{param_name}' not in model, skipping")

  # Apply polydispersity configuration
  if polydispersity:
    pd_params = fitter.get_polydisperse_parameters()
    pd_allowed_keys = {"pd_width", "pd_type", "pd_n", "pd_nsigma", "vary"}
    has_pd_config = False

    for param_name, pd_config in polydispersity.items():
      if param_name not in pd_params:
        print(
          f"Warning: param '{param_name}' does not support polydispersity, skipping"
        )
        continue

      # Filter to allowed keys for set_pd_param
      filtered_pd = {k: v for k, v in pd_config.items() if k in pd_allowed_keys}
      if filtered_pd:
        fitter.set_pd_param(param_name, **filtered_pd)
        has_pd_config = True
        print(f"Configured polydispersity for '{param_name}': {filtered_pd}")

    # Enable polydispersity if any config was applied
    if has_pd_config:
      fitter.enable_polydispersity(True)
      print(f"Polydispersity enabled: {fitter.is_polydispersity_enabled()}")

  # Parameters before fitting
  print("Parameters before fitting:")
  print(fitter.params.items())

  try:
    fit_result = fitter.fit(engine=engine, method=method)
  except Exception as e:
    raise RuntimeError(f"Fitting failed for model '{model}': {e}") from e

  plot = fitter.plot_results(show_residuals=True, log_scale=plot_log_scale)
  plot.write_image(str(out_dir / "fit_plot.png"))

  return {
    "fit": str(fit_result),
    "artifacts": {"plot": str(out_dir / "fit_plot.png")},
  }


if __name__ == "__main__":
  # CLI for local testing: python fitting-with-custom-model.py <input.csv> [model]
  import sys

  if len(sys.argv) < 2:
    raise SystemExit("Usage: python fitting-with-custom-model.py <input_csv> [model]")

  print(
    run(
      input_csv=sys.argv[1],
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
