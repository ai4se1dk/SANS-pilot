"""Strict MCP request schemas shared by SANS scientific tools."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictRequest(BaseModel):
  """Base model that rejects misspelled or obsolete request fields."""

  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class UploadDataSource(StrictRequest):
  """A file uploaded by the current LibreChat user."""

  kind: Literal["upload"]
  file: str = Field(min_length=1)
  dataset_index: int | None = Field(default=None, ge=0)


class ExampleDataSource(StrictRequest):
  """A curated one-dimensional dataset bundled with sans-fitter."""

  kind: Literal["example"]
  name: str = Field(min_length=1)


SimulationParameter = int | float | str | bool


class SimulationDataSource(StrictRequest):
  """A deterministic synthetic SANS dataset with known ground truth."""

  kind: Literal["simulation"]
  model: str = Field(min_length=1)
  parameters: dict[str, SimulationParameter] = Field(default_factory=dict)
  q_min: float = 0.005
  q_max: float = 0.5
  points: int = Field(default=100, le=5_000)
  noise: float = 0.02
  seed: int | None = None
  relative_resolution: float | None = None


DataSource = Annotated[
  UploadDataSource | ExampleDataSource | SimulationDataSource,
  Field(discriminator="kind"),
]


class DataOperation(StrictRequest):
  """One ordered dataset/dataset or dataset/scalar operation."""

  operation: Literal["add", "subtract", "multiply", "divide"]
  operand: str | None = Field(default=None, min_length=1)
  scalar: float | None = None

  @model_validator(mode="after")
  def validate_operand(self) -> DataOperation:
    if (self.operand is None) == (self.scalar is None):
      raise ValueError("Provide exactly one of operand or scalar.")
    return self


class DatasetPipeline(StrictRequest):
  """A data source followed by optional arithmetic and Q-range selection."""

  primary: DataSource
  auxiliary: dict[str, DataSource] = Field(default_factory=dict)
  operations: list[DataOperation] = Field(default_factory=list, max_length=20)
  q_min: float | None = None
  q_max: float | None = None

  @model_validator(mode="after")
  def validate_pipeline(self) -> DatasetPipeline:
    empty_aliases = [alias for alias in self.auxiliary if not alias.strip()]
    if empty_aliases:
      raise ValueError("Auxiliary dataset aliases must be non-empty.")

    referenced = {
      operation.operand
      for operation in self.operations
      if operation.operand is not None
    }
    unknown = referenced - set(self.auxiliary)
    if unknown:
      raise ValueError(
        "Operations reference unknown auxiliary datasets: " + ", ".join(sorted(unknown))
      )
    return self


StructureFactorName = str


class AtomicModel(StrictRequest):
  """One sasmodels form factor with an optional interaction model."""

  kind: Literal["atomic"]
  model: str = Field(min_length=1)
  structure_factor: StructureFactorName | None = None
  radius_effective_mode: str = "unconstrained"
  parameter_links: dict[str, str] = Field(default_factory=dict, max_length=20)


class ModelComponent(StrictRequest):
  """One uniquely named component in a composite model."""

  alias: str
  model: str = Field(min_length=1)
  structure_factor: StructureFactorName | None = None


class CompositeModel(StrictRequest):
  """An additive or multiplicative composition of sasmodels components."""

  kind: Literal["composite"]
  operation: str = "+"
  components: list[ModelComponent] = Field(max_length=10)
  shared_parameters: list[str] = Field(default_factory=list, max_length=20)
  parameter_links: dict[str, str] = Field(default_factory=dict, max_length=20)

  @model_validator(mode="after")
  def validate_components(self) -> CompositeModel:
    aliases = [component.alias for component in self.components]
    if len(aliases) != len(set(aliases)):
      raise ValueError("Composite component aliases must be unique.")
    return self


ModelSpecification = Annotated[
  AtomicModel | CompositeModel,
  Field(discriminator="kind"),
]


class ParameterOverride(StrictRequest):
  """An explicit value, bounds, or vary setting for one model parameter."""

  value: float | None = None
  min: float | None = None
  max: float | None = None
  vary: bool | None = None


class PolydispersitySetting(StrictRequest):
  """Polydispersity configuration for one supported model parameter."""

  pd_width: float
  pd_type: str = "gaussian"
  pd_n: int = Field(default=35, le=200)
  pd_nsigma: float = 3.0
  vary: bool = False


class OptimizationSettings(StrictRequest):
  """Point-estimate settings passed to ``SANSFitter.fit``."""

  mode: Literal["optimization"] = "optimization"
  engine: str = "bumps"
  method: str | None = None
  options: dict[str, SimulationParameter] = Field(default_factory=dict, max_length=30)


class BayesianSettings(StrictRequest):
  """Settings passed to ``SANSFitter.fit_bayesian``."""

  mode: Literal["bayesian"]
  method: str = "dream"
  samples: int = Field(default=5_000, le=50_000)
  burn: int = Field(default=200, le=5_000)
  thin: int = Field(default=1, le=100)
  pop: int = Field(default=10, le=50)
  options: dict[str, SimulationParameter] = Field(default_factory=dict, max_length=30)


FitSettings = Annotated[
  OptimizationSettings | BayesianSettings,
  Field(discriminator="mode"),
]


class FitArtifactOptions(StrictRequest):
  """Optional fit files and plot controls."""

  include_results_csv: bool = False
  include_sasview_parameters: bool = True
  include_posterior_chain: bool = False
  posterior_plots: list[
    Literal["pairs", "distribution", "predictive", "correlations", "trace"]
  ] = Field(default_factory=lambda: ["predictive"], max_length=5)
  posterior_parameters: list[str] | None = Field(default=None, max_length=20)
  posterior_predictive_style: Literal["band", "draws", "band+draws"] = "band"
  posterior_predictive_draws: int = Field(default=50, ge=1, le=200)
  plot_log_scale: bool = True
  show_components: bool | None = None


class FitSansModelRequest(StrictRequest):
  """Complete typed request for a sasmodels fit."""

  pipeline: DatasetPipeline
  model: ModelSpecification
  parameters: dict[str, ParameterOverride] = Field(default_factory=dict)
  polydispersity: dict[str, PolydispersitySetting] = Field(
    default_factory=dict,
    max_length=20,
  )
  fit: FitSettings = Field(default_factory=OptimizationSettings)
  artifacts: FitArtifactOptions = Field(default_factory=FitArtifactOptions)


class AutomaticInversion(StrictRequest):
  """Automatically select the P(r) basis size and regularization."""

  mode: Literal["automatic"] = "automatic"


class ManualInversion(StrictRequest):
  """Use an explicitly selected P(r) basis and regularization."""

  mode: Literal["manual"]
  n_terms: int = Field(le=50)
  alpha: float


InversionSelection = Annotated[
  AutomaticInversion | ManualInversion,
  Field(discriminator="mode"),
]


class InvertSansPrRequest(StrictRequest):
  """Typed model-free pair-distance-distribution inversion request."""

  pipeline: DatasetPipeline
  d_max: float = Field(description="Maximum particle dimension in Å.")
  selection: InversionSelection = Field(default_factory=AutomaticInversion)
  fit_background: bool = True
  background: float = 0.0
  regularizer: str = "corrected"
  r_points: int = Field(default=101, le=2_001)
  include_pr_csv: bool = False
  plot_log_scale: bool = True


class ScanSansDmaxRequest(StrictRequest):
  """Typed bounded Dmax exploration request."""

  pipeline: DatasetPipeline
  d_max_guess: float = Field(description="Central Dmax estimate in Å.")
  d_min: float | None = None
  d_max: float | None = None
  points: int = Field(default=25, le=101)
  n_terms: int | None = Field(default=None, le=50)
  alpha: float | None = None
  refit_alpha: bool = False
  fit_background: bool = True
  background: float = 0.0
  regularizer: str = "corrected"
  plot_quantity: str = "all"


class SimulateSansDataRequest(StrictRequest):
  """Generate and optionally export one reproducible synthetic dataset."""

  source: SimulationDataSource
  include_csv: bool = False
  plot_log_scale: bool = True


class SimulateSansPairRequest(StrictRequest):
  """Generate a matched sample/background pair on the same Q grid."""

  source: SimulationDataSource
  background_level: float = 0.5
  include_csv: bool = False
  plot_log_scale: bool = True
