"""Typed model-free P(r) inversion and Dmax exploration services."""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path
from typing import Any

from sans_fitter import pr_inversion

from sans_pilot.analyses._fitting_helpers import (
  filter_actionable_warnings,
  normalize_scalar,
  normalize_value,
)
from sans_pilot.datasets import inspect_data, log_plot_warnings, prepare_dataset
from sans_pilot.runtime import render_runtime, scientific_runtime
from sans_pilot.schemas import (
  InvertSansPrRequest,
  ManualInversion,
  ScanSansDmaxRequest,
)

SCHEMA_VERSION = "1.0"


def _artifact_metadata(artifacts: dict[str, Path]) -> list[dict[str, str]]:
  mime_types = {".png": "image/png", ".csv": "text/csv"}
  return [
    {"name": name, "mime_type": mime_types[path.suffix.lower()]}
    for name, path in artifacts.items()
  ]


def _format_pr_result(result: Any) -> dict[str, Any]:
  return {
    "d_max_angstrom": normalize_scalar(result.d_max),
    "n_terms": normalize_scalar(result.n_terms),
    "alpha": normalize_scalar(result.alpha),
    "regularizer": result.regularizer,
    "background": {
      "value": normalize_scalar(result.background),
      "fitted": result.background_fitted,
      "stderr": normalize_scalar(result.background_err),
    },
    "rg_angstrom": normalize_scalar(result.rg),
    "i0": normalize_scalar(result.i0),
    "data_chi_squared": normalize_scalar(result.data_chisq),
    "effective_dof": normalize_scalar(result.effective_dof),
    "regularization_penalty": normalize_scalar(result.regularization_penalty),
    "oscillations": normalize_scalar(result.oscillations),
    "positive_fraction": normalize_scalar(result.positive_fraction),
    "sigma_positive_fraction": normalize_scalar(result.sigma_positive_fraction),
    "condition_number": normalize_scalar(result.condition_number),
    "rank": normalize_scalar(result.rank),
    "points_used": normalize_scalar(result.n_points_used),
    "points_available": int(result.accepted.size),
    "points_dropped": normalize_scalar(result.n_dropped_points),
    "uncertainties_fabricated": result.uncertainties_fabricated,
  }


def invert_sans_pr_service(
  request: InvertSansPrRequest,
  *,
  user_id: str | None,
  output_dir: str | Path,
) -> dict[str, Any]:
  """Run automatic or manual P(r) inversion and write bounded artifacts."""
  prepared = prepare_dataset(request.pipeline, user_id=user_id)
  data_summary = inspect_data(prepared.data)
  output_path = Path(output_dir)
  output_path.mkdir(parents=True, exist_ok=True)

  with scientific_runtime(), warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    if isinstance(request.selection, ManualInversion):
      result = pr_inversion.invert(
        prepared.data,
        d_max=request.d_max,
        n_terms=request.selection.n_terms,
        alpha=request.selection.alpha,
        fit_background=request.fit_background,
        background=request.background,
        r_points=request.r_points,
        regularizer=request.regularizer,
      )
    else:
      result = pr_inversion.auto_invert(
        prepared.data,
        d_max=request.d_max,
        fit_background=request.fit_background,
        background=request.background,
        r_points=request.r_points,
        regularizer=request.regularizer,
      )

    artifacts: dict[str, Path] = {}
    pr_plot = output_path / "pr_distribution.png"
    with render_runtime():
      result.plot_pr(show=False).write_image(pr_plot)
    artifacts[pr_plot.name] = pr_plot
    fit_plot = output_path / "pr_iq_fit.png"
    with render_runtime():
      result.plot_fit(
        prepared.data,
        show=False,
        log_scale=request.plot_log_scale,
      ).write_image(fit_plot)
    artifacts[fit_plot.name] = fit_plot
    if request.include_pr_csv:
      csv_path = output_path / "pr_result.csv"
      with contextlib.redirect_stdout(io.StringIO()):
        result.save_csv(str(csv_path))
      artifacts[csv_path.name] = csv_path

  warning_messages = filter_actionable_warnings(
    [
      *prepared.warnings,
      *log_plot_warnings(prepared.data, log_scale=request.plot_log_scale),
      *(str(item.message) for item in captured),
    ]
  )
  return {
    "summary": {
      "schema_version": SCHEMA_VERSION,
      "analysis": "pr_inversion",
      "source": prepared.source,
      "auxiliary_sources": prepared.auxiliary_sources,
      "data": data_summary,
      "preprocessing": prepared.preprocessing,
      "configuration": {
        "selection": request.selection.model_dump(),
        "fit_background": request.fit_background,
        "fixed_background": (
          request.background if not request.fit_background else None
        ),
        "regularizer": request.regularizer,
        "r_points": request.r_points,
      },
      "result": _format_pr_result(result),
      "warnings": warning_messages,
      "artifacts": _artifact_metadata(artifacts),
    },
    "artifacts": artifacts,
  }


def _format_dmax_scan(scan: Any) -> dict[str, Any]:
  """Serialize the values returned by sans-fitter's Dmax scan."""
  return {
    "n_terms": normalize_scalar(scan.n_terms),
    "successful_points": int(scan.d_max_values.size),
    "d_max_angstrom": normalize_value(scan.d_max_values),
    "data_chi_squared": normalize_value(scan.data_chisq),
    "rg_angstrom": normalize_value(scan.rg),
    "i0": normalize_value(scan.i0),
    "oscillations": normalize_value(scan.oscillations),
    "positive_fraction": normalize_value(scan.positive_fraction),
    "sigma_positive_fraction": normalize_value(scan.sigma_positive_fraction),
    "background": normalize_value(scan.background),
    "alpha": normalize_value(scan.alpha),
    "failures": [
      {"d_max_angstrom": normalize_scalar(d_max), "message": message[:1_000]}
      for d_max, message in scan.failures
    ],
  }


def scan_sans_dmax_service(
  request: ScanSansDmaxRequest,
  *,
  user_id: str | None,
  output_dir: str | Path,
) -> dict[str, Any]:
  """Explore a bounded Dmax range under a process-level safety lock."""
  prepared = prepare_dataset(request.pipeline, user_id=user_id)
  data_summary = inspect_data(prepared.data)
  output_path = Path(output_dir)
  output_path.mkdir(parents=True, exist_ok=True)

  with scientific_runtime(), warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    scan = pr_inversion.explore_dmax(
      prepared.data,
      d_max=request.d_max_guess,
      n_terms=request.n_terms,
      alpha=request.alpha,
      dmin=request.d_min,
      dmax=request.d_max,
      n_points=request.points,
      refit_alpha=request.refit_alpha,
      fit_background=request.fit_background,
      regularizer=request.regularizer,
      background=request.background,
    )
    plot_path = output_path / "dmax_scan.png"
    with render_runtime():
      scan.plot(quantity=request.plot_quantity, show=False).write_image(plot_path)

  formatted_scan = _format_dmax_scan(scan)
  warnings_out = filter_actionable_warnings(
    [*prepared.warnings, *(str(item.message) for item in captured)]
  )
  artifacts = {plot_path.name: plot_path}
  return {
    "summary": {
      "schema_version": SCHEMA_VERSION,
      "analysis": "dmax_scan",
      "source": prepared.source,
      "auxiliary_sources": prepared.auxiliary_sources,
      "data": data_summary,
      "preprocessing": prepared.preprocessing,
      "configuration": request.model_dump(exclude={"pipeline"}),
      "result": formatted_scan,
      "warnings": warnings_out,
      "artifacts": _artifact_metadata(artifacts),
    },
    "artifacts": artifacts,
  }
