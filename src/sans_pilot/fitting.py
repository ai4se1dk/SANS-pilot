"""Thin MCP adapter for point-estimate and Bayesian SANS fitting."""

from __future__ import annotations

import contextlib
import io
import warnings
from pathlib import Path
from typing import Any, cast

from sans_fitter import SANSFitter

from sans_pilot.analyses._fitting_helpers import (
  build_parameter_export,
  filter_actionable_warnings,
  format_fit_result,
  format_posterior_summary,
  serialize_sasview_parameter_values,
)
from sans_pilot.datasets import (
  PreparedData,
  inspect_data,
  log_plot_warnings,
  prepare_dataset,
)
from sans_pilot.fit_artifacts import write_posterior_artifacts
from sans_pilot.models import (
  apply_parameter_links,
  apply_parameter_overrides,
  apply_polydispersity,
  construct_model,
  resolved_model_configuration,
  resolved_polydispersity_configuration,
)
from sans_pilot.runtime import render_runtime, scientific_runtime
from sans_pilot.schemas import (
  AtomicModel,
  BayesianSettings,
  CompositeModel,
  FitSansModelRequest,
  OptimizationSettings,
)

SCHEMA_VERSION = "1.0"


def _run_fit(fitter: SANSFitter, request: FitSansModelRequest) -> dict[str, Any]:
  """Pass the requested fit settings directly to sans-fitter."""
  if isinstance(request.fit, BayesianSettings):
    return fitter.fit_bayesian(
      method=request.fit.method,
      samples=request.fit.samples,
      burn=request.fit.burn,
      thin=request.fit.thin,
      pop=request.fit.pop,
      **request.fit.options,
    )

  settings = cast(OptimizationSettings, request.fit)
  return fitter.fit(
    engine=settings.engine,  # type: ignore[arg-type]
    method=settings.method,
    **settings.options,
  )


def _write_fit_artifacts(
  fitter: SANSFitter,
  request: FitSansModelRequest,
  *,
  output_dir: Path,
  fit_result: dict[str, Any],
  warning_messages: list[str],
) -> dict[str, Path]:
  """Serialize plots/files provided by the configured sans-fitter result."""
  options = request.artifacts
  warning_messages.extend(
    log_plot_warnings(fitter.data, log_scale=options.plot_log_scale)
  )
  show_components = options.show_components
  if show_components is None:
    show_components = (
      isinstance(request.model, CompositeModel) and request.model.operation == "+"
    )

  fit_plot_path = output_dir / "fit_plot.png"
  with render_runtime():
    fitter.plot_results(
      show_residuals=True,
      log_scale=options.plot_log_scale,
      show=False,
      show_components=show_components,
    ).write_image(fit_plot_path)
  artifacts: dict[str, Path] = {fit_plot_path.name: fit_plot_path}

  if options.include_results_csv:
    results_path = output_dir / "fit_results.csv"
    fitter.save_results(str(results_path))
    artifacts[results_path.name] = results_path

  if options.include_sasview_parameters:
    if isinstance(request.model, AtomicModel):
      model_name = request.model.model
      if request.model.structure_factor is not None:
        model_name = f"{model_name}@{request.model.structure_factor}"
      rows = build_parameter_export(
        model=model_name,
        params=fitter.params,
        fit_result=fit_result,
      )
      path = output_dir / "sasview_parameter_values.txt"
      path.write_text(serialize_sasview_parameter_values(rows), encoding="utf-8")
      artifacts[path.name] = path
    else:
      warning_messages.append(
        "SasView parameter-value export was omitted because the compact "
        "single-model format cannot represent composite models."
      )

  if isinstance(request.fit, BayesianSettings):
    artifacts.update(
      write_posterior_artifacts(fitter, output_dir=output_dir, options=options)
    )
  return artifacts


def _artifact_metadata(artifacts: dict[str, Path]) -> list[dict[str, str]]:
  mime_types = {
    ".png": "image/png",
    ".csv": "text/csv",
    ".txt": "text/plain",
  }
  return [
    {
      "name": name,
      "mime_type": mime_types.get(path.suffix.lower(), "application/octet-stream"),
    }
    for name, path in artifacts.items()
  ]


def run_typed_fit(
  request: FitSansModelRequest,
  *,
  user_id: str | None,
  output_dir: str | Path,
) -> dict[str, Any]:
  """Configure sans-fitter, execute it, and serialize its native result."""
  prepared: PreparedData = prepare_dataset(request.pipeline, user_id=user_id)
  fitter = SANSFitter()
  output_path = Path(output_dir)
  output_path.mkdir(parents=True, exist_ok=True)
  artifact_warnings: list[str] = []

  with scientific_runtime(), warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    with contextlib.redirect_stdout(io.StringIO()):
      fitter.set_data(prepared.data)
      construct_model(fitter, request.model)
      apply_parameter_overrides(fitter, request.parameters)
      apply_polydispersity(fitter, request.polydispersity)
      apply_parameter_links(fitter, request.model)
      fit_result = _run_fit(fitter, request)
      artifacts = _write_fit_artifacts(
        fitter,
        request,
        output_dir=output_path,
        fit_result=fit_result,
        warning_messages=artifact_warnings,
      )

  warning_messages = filter_actionable_warnings(
    [
      *prepared.warnings,
      *artifact_warnings,
      *(str(item.message) for item in captured),
    ]
  )
  result = format_fit_result(fit_result)
  if isinstance(request.fit, BayesianSettings):
    result["posterior"] = format_posterior_summary(fitter.get_posterior())

  return {
    "summary": {
      "schema_version": SCHEMA_VERSION,
      "analysis": "model_fit",
      "source": prepared.source,
      "auxiliary_sources": prepared.auxiliary_sources,
      "data": inspect_data(prepared.data),
      "preprocessing": prepared.preprocessing,
      "model": resolved_model_configuration(fitter, request.model),
      "polydispersity": resolved_polydispersity_configuration(
        fitter, request.polydispersity
      ),
      "fit": request.fit.model_dump(),
      "result": result,
      "warnings": warning_messages,
      "artifacts": _artifact_metadata(artifacts),
    },
    "artifacts": artifacts,
  }
