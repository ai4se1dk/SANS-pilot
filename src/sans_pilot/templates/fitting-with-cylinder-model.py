"""Cylinder model fitting template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from sans_fitter import SANSFitter

TEMPLATE_NAME = "fitting-with-cylinder-model"
TEMPLATE_DESCRIPTION = (
  "Fit SANS data using a cylinder model. "
  "Template parameters: input_csv (str, required), "
  "engine (bumps|lmfit, default: bumps), method (str, default: amoeba), "
  "plot_log_scale (bool, default: True). "
  "Model parameters (via param_overrides): "
  "radius (default: 20, range: 1-100, vary), "
  "length (default: 400, range: 10-1000, vary), "
  "sld (default: 4.0, fixed), sld_solvent (default: 1.0, fixed), "
  "scale (default: 1.0, range: 0.1-10, vary), "
  "background (default: 0.001, range: 0-1, vary)."
)


def run(
  *,
  input_csv: str | Path,
  output_dir: str | Path,
  engine: Literal["bumps", "lmfit"] = "bumps",
  method: str | None = "amoeba",
  plot_log_scale: bool = True,
  param_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
  """Fit cylinder model to SANS data.

  Args:
    input_csv: Path to the CSV data file.
    output_dir: Directory for output artifacts.
    engine: Fitting engine ('bumps' or 'lmfit').
    method: Optimization method.
    plot_log_scale: Use log scale for plot.
    param_overrides: Override default model parameters.

  Returns:
    Dict with template name, input path, engine, method, fit results, and artifacts.
  """

  input_path = Path(input_csv)
  out_dir = Path(output_dir)
  out_dir.mkdir(parents=True, exist_ok=True)

  fitter = SANSFitter()
  fitter.load_data(str(input_path))
  fitter.set_model("cylinder")

  defaults: dict[str, dict[str, Any]] = {
    "radius": {"value": 20, "min": 1, "max": 100, "vary": True},
    "length": {"value": 400, "min": 10, "max": 1000, "vary": True},
    "sld": {"value": 4.0, "vary": False},
    "sld_solvent": {"value": 1.0, "vary": False},
    "scale": {"value": 1.0, "min": 0.1, "max": 10, "vary": True},
    "background": {"value": 0.001, "min": 0, "max": 1, "vary": True},
  }

  if param_overrides:
    for param_name, overrides in param_overrides.items():
      if param_name in defaults:
        defaults[param_name] = {**defaults[param_name], **overrides}
      else:
        defaults[param_name] = {**overrides}

  for param_name, spec in defaults.items():
    fitter.set_param(param_name, **spec)

  fit_result = fitter.fit(engine=engine, method=method)

  plot = fitter.plot_results(show_residuals=True, log_scale=plot_log_scale)
  plot.write_image(str(out_dir / "fit_plot.png"))

  return {
    "template": "fitting-with-cylinder-model",
    "input_csv": str(input_path),
    "engine": engine,
    "method": method,
    "fit": str(fit_result),
    "artifacts": {"plot": str(out_dir / "fit_plot.png")},
  }


if __name__ == "__main__":
  # CLI for local testing: python fitting-with-cylinder-model.py <input.csv>
  import sys

  if len(sys.argv) < 2:
    raise SystemExit("Usage: python fitting-with-cylinder-model.py <input_csv>")

  print(
    run(
      input_csv=sys.argv[1],
      output_dir=Path.cwd() / "fit-output",
    )
  )
