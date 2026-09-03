# SANS-pilot

MCP server for reduced one-dimensional Small-Angle Neutron Scattering data
analysis, powered by [SANS-fitter](https://github.com/ai4se1dk/SANS-fitter).

## Scientific tools

| Tool                          | Purpose                                                            |
| ----------------------------- | ------------------------------------------------------------------ |
| `describe-sans-capabilities`  | Describe supported workflows and scientific limitations            |
| `list-supported-sans-formats` | List accepted reduced 1D community formats                         |
| `list-uploaded-sans-files`    | List current-user uploads without exposing file contents           |
| `inspect-sans-data`           | Inspect an upload, example, or simulation                          |
| `plot-sans-data`              | Plot measured data without a model, fit curve, or residuals        |
| `process-sans-data`           | Apply arithmetic/Q selection and return processed CSV data         |
| `list-sans-models`            | List exact sasmodels names                                         |
| `get-sans-model-parameters`   | Discover an exact atomic, interacting, or composite model contract |
| `list-structure-factors`      | List supported inter-particle interaction models                   |
| `get-polydispersity-options`  | List size-distribution types and defaults                          |
| `fit-sans-model`              | Run optimization or Bayesian fitting through sans-fitter           |
| `scan-sans-dmax`              | Explore Dmax using Rg, I(0), fit-quality, and positivity trends    |
| `invert-sans-pr`              | Recover the model-free real-space pair distribution P(r)           |
| `list-sans-examples`          | Discover curated measured and simulated datasets                   |
| `inspect-sans-example`        | Inspect an example and its suggested configuration                 |
| `simulate-sans-data`          | Generate synthetic data with known truth                           |
| `simulate-sans-pair`          | Generate a matched sample/background pair                          |
| `read-sans-artifact`          | Reopen a user-scoped image or chunked CSV/text artifact            |

## Data pipeline

All data tools use a typed `pipeline`. The primary source may be a user upload,
a bundled example, or a simulation:

```json
{ "primary": { "kind": "upload", "file": "stored-data-name.xml" } }
```

```json
{ "primary": { "kind": "example", "name": "protein" } }
```

```json
{
  "primary": {
    "kind": "simulation",
    "model": "sphere",
    "parameters": { "radius": 50 },
    "seed": 42
  }
}
```

Optional `auxiliary` sources and ordered `operations` support `add`,
`subtract`, `multiply`, and `divide` with another dataset or a scalar. Optional
`q_min` and `q_max` select the active scientific range. Arithmetic behavior,
including uncertainty, unit, and resolution propagation, is provided directly
by `sans-fitter`.

### Plot without fitting

```json
{
  "pipeline": {
    "primary": { "kind": "upload", "file": "simulated_sans_data.csv" }
  },
  "log_scale": true
}
```

`plot-sans-data` returns metadata, an inline MCP image for immediate display,
and a lazy resource URI for `sans_data_plot.png`; it never selects a model or
performs a fit.

## Model discovery and fitting

Call `get-sans-model-parameters` with the exact model specification you intend
to fit. It returns parameter names, defaults, bounds, polydispersity support,
component aliases, and links reported by the configured sans-fitter model.

### Atomic model fit

`fit-sans-model` accepts one `request` object:

```json
{
  "request": {
    "pipeline": {
      "primary": { "kind": "upload", "file": "simulated_sans_data.csv" },
      "q_min": 0.01,
      "q_max": 0.3
    },
    "model": { "kind": "atomic", "model": "cylinder" },
    "parameters": {
      "radius": { "value": 20, "min": 1, "max": 200, "vary": true },
      "length": { "value": 400, "min": 10, "max": 4000, "vary": true },
      "scale": { "value": 1, "min": 0, "max": 10, "vary": true },
      "background": { "value": 0.001, "min": 0, "max": 1, "vary": true }
    },
    "fit": { "mode": "optimization", "engine": "bumps", "method": "amoeba" }
  }
}
```

The selected engine and method are passed directly to `sans-fitter`. Fit
objectives, uncertainties, optimizer status, warnings, and errors retain their
`sans-fitter` meanings and are not reinterpreted by the MCP server.

### Structure factor and polydispersity

An interacting atomic model puts the structure factor in the model object;
its parameters use the same `parameters` map:

```json
{
  "model": {
    "kind": "atomic",
    "model": "sphere",
    "structure_factor": "hardsphere",
    "radius_effective_mode": "link_radius"
  },
  "polydispersity": {
    "radius": {
      "pd_width": 0.1,
      "pd_type": "gaussian",
      "pd_n": 35,
      "pd_nsigma": 3,
      "vary": false
    }
  }
}
```

Supported structure factors are `hardsphere`, `hayter_msa`, `squarewell`, and
`stickyhardsphere`. Supported distributions are `gaussian`, `rectangle`,
`lognormal`, `schulz`, and `boltzmann`.

### Composite model

Composite models combine uniquely named components. `shared_parameters` and
`parameter_links` configure the equality mechanisms provided by sans-fitter.

```json
{
  "kind": "composite",
  "operation": "+",
  "components": [
    { "alias": "small", "model": "sphere" },
    { "alias": "long", "model": "cylinder" }
  ],
  "shared_parameters": ["sld", "sld_solvent"],
  "parameter_links": {}
}
```

Composite models and parameter links require BUMPS point-estimate fitting.
Additive component curves are included in the fit plot by default.

### Bayesian fit

```json
{
  "fit": {
    "mode": "bayesian",
    "samples": 5000,
    "burn": 200,
    "thin": 1,
    "pop": 10
  },
  "artifacts": {
    "posterior_plots": ["predictive", "pairs", "trace"],
    "include_posterior_chain": false
  }
}
```

Bayesian fitting uses the BUMPS DREAM integration provided by `sans-fitter`.
The compact response serializes the posterior summary and diagnostics returned
by `sans-fitter`; raw samples are not placed in model context.

Every fit returns compact structured JSON, inline MCP image content for plots,
and lazy MCP resource URIs for all generated files. When browser downloads are
configured, artifact metadata also includes a signed `download_url`. Atomic
fits include links for `sasview_parameter_values.txt` by default. CSV and text
artifact bytes are not included in the original tool response. `fit_results.csv`
and `posterior_chain.csv` are generated only when explicitly requested. MCP
resource URIs are opaque and user-scoped; non-image artifacts remain lazy so
their contents do not consume model context.

## Model-free P(r) inversion

`scan-sans-dmax` exposes sans-fitter's Dmax exploration. The scan returns
arrays for Rg, I(0), data chi-squared, oscillations, positivity, background,
and alpha plus `dmax_scan.png`. Sans-fitter documents a good Dmax as showing an
Rg/I(0) plateau and a minimum in the data chi-squared.

`invert-sans-pr` supports automatic selection of basis terms and regularization
or a manual mode that requires both `n_terms` and `alpha`:

```json
{
  "request": {
    "pipeline": { "primary": { "kind": "example", "name": "protein" } },
    "d_max": 120,
    "selection": { "mode": "automatic" },
    "fit_background": false,
    "regularizer": "corrected",
    "include_pr_csv": false,
    "plot_log_scale": false
  }
}
```

The result includes Dmax, Rg, I(0), background treatment, data chi-squared,
effective degrees of freedom, oscillations, positivity fractions, matrix
condition/rank diagnostics, and whether uncertainties were fabricated. It
returns P(r) and I(Q)/residual plots; numerical P(r) CSV is opt-in. Pinhole dQ
is ignored and slit smearing is unsupported by sans-fitter 0.3 inversion.

Buffer-subtracted protein data normally uses `fit_background=false` because a
fitted flat background can absorb I(0) and bias Rg.

## Curated examples and simulation

`list-sans-examples` can filter by tag and returns descriptions, suggested
models and parameters, structure factors, polydispersity, and caveats.
`inspect-sans-example` loads live metadata. Measured examples have
`known_truth=null`; suggested values are starting points, not results.

`simulate-sans-data` and `simulate-sans-pair` pass simulation settings to
`sans-fitter`; set an explicit seed when reproducible output is required. They
return generation truth separately from any later fitted estimate. The pair
tool produces independent noise on one shared Q grid, suitable for subtraction
tests. Plots are returned by default and CSV files only when requested.

## Supported data scope

The server accepts reduced 1D columnar text, NIST/SasView ASCII, CanSAS XML,
NXcanSAS/HDF5, and Anton Paar PDH data. Containers are type-checked after
loading. 2D SANS and SESANS are rejected with actionable messages.

## Configuration

| Variable                          | Default                | Description                                                        |
| --------------------------------- | ---------------------- | ------------------------------------------------------------------ |
| `UPLOAD_DIR`                      | `/uploads`             | User-uploaded data directory                                       |
| `SANS_PILOT_RUNS_DIR`             | `/tmp/sans-pilot-runs` | Shared workspace root for artifacts and durable token manifests    |
| `SANS_PILOT_ARTIFACT_TTL_SECONDS` | `86400`                | Artifact-token lifetime in seconds; `0` disables expiration         |
| `SANS_PILOT_PUBLIC_BASE_URL`      | unset                  | Public HTTP(S) URL or absolute path for browser artifact downloads  |
| `SANS_PILOT_DOWNLOAD_SIGNING_KEY` | unset                  | Secret used to sign browser artifact download capabilities          |
| `SANS_PILOT_MAX_WORKERS`          | `2`                    | Maximum concurrent scientific worker processes                     |
| `SANS_PILOT_TOOL_TIMEOUT_SECONDS` | `1800`                 | Hard execution timeout per worker; `0` disables it                  |
| `API_TOKEN`                       | unset                  | Optional bearer token                                              |

Artifact manifests are stored under `SANS_PILOT_RUNS_DIR/.registry`. When the
runs directory is persistent and shared by all replicas, earlier artifacts can
be reopened after process or pod restarts. `read-sans-artifact` returns images
as MCP image content and CSV/text artifacts in bounded byte chunks.

When both download settings are configured, artifact metadata includes a
non-expiring, HMAC-signed `download_url`. The URL remains valid while the
artifact exists and the signing key is unchanged. It is a bearer capability:
anyone who obtains the URL can download the artifact, so it must not be logged
or shared unintentionally. A future version should add configurable link
expiration.

Long-running scientific calls execute in isolated worker processes. Cancelling
the MCP request terminates the worker and removes its partial artifact
workspace. The hard tool timeout provides cleanup when a client does not
propagate cancellation.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
sans-pilot
```

```bash
docker build -f Dockerfile.dev -t sans-pilot .
docker run -p 8001:8001 -e API_TOKEN="your-token" sans-pilot
```

Run automated checks with:

```bash
ruff check src test
pyright
pytest
```
