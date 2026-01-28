# SANS-pilot

MCP server for SANS (Small-Angle Neutron Scattering) data analysis, powered by [SANS-fitter](https://github.com/ai4se1dk/SANS-fitter).

## Tools

| Tool                              | Description                                                                  |
| --------------------------------- | ---------------------------------------------------------------------------- |
| `describe-possibilities`          | Describe server capabilities                                                 |
| `list-sans-models`                | List available sasmodels for fitting (e.g., cylinder, sphere, ellipsoid)     |
| `get-model-parameters`            | Get parameter specs for a model (value, min, max, vary, description)         |
| `list-structure-factors`          | List available structure factors for inter-particle interactions             |
| `get-structure-factor-parameters` | Get parameters for a form_factor@structure_factor product model              |
| `get-polydisperse-parameters`     | Get parameters that support polydispersity for a model                       |
| `get-polydispersity-options`      | Get available PD distribution types (gaussian, lognormal, etc.) and defaults |
| `list-uploaded-files`             | List uploaded data files (optional: filter by extension, limit)              |
| `list-analyses`                   | List available analysis types with parameters                                |
| `run-analysis`                    | Run analysis, returns fit results and plot                                   |

## Typical Workflow

1. **Discover models**: Call `list-sans-models` to see available sasmodels
2. **Get parameters**: Call `get-model-parameters` with model name to see default params
3. **Find data**: Call `list-uploaded-files` to find your CSV data file
4. **Run fit**: Call `run-analysis` with analysis name, input file, model, and param overrides

### Example: Fitting cylinder model

```json
{
  "name": "fitting-with-custom-model",
  "parameters": {
    "input_csv": "simulated_sans_data.csv",
    "model": "cylinder",
    "engine": "bumps",
    "method": "amoeba",
    "param_overrides": {
      "radius": { "value": 20, "min": 1, "max": 200, "vary": true },
      "length": { "value": 400, "min": 10, "max": 4000, "vary": true },
      "scale": { "value": 1.0, "min": 0.0, "max": 10, "vary": true },
      "background": { "value": 0.001, "min": 0, "max": 1, "vary": true }
    }
  }
}
```

### Example: Fitting with polydispersity

Use `get-polydisperse-parameters` to see which parameters support size distributions, then add a `polydispersity` config:

```json
{
  "name": "fitting-with-custom-model",
  "parameters": {
    "input_csv": "simulated_sans_data.csv",
    "model": "cylinder",
    "engine": "bumps",
    "method": "amoeba",
    "param_overrides": {
      "radius": { "value": 20, "min": 1, "max": 200, "vary": true },
      "length": { "value": 400, "min": 10, "max": 4000, "vary": true },
      "scale": { "value": 1.0, "vary": true },
      "background": { "value": 0.001, "vary": true }
    },
    "polydispersity": {
      "radius": {
        "pd_width": 0.1,
        "pd_type": "gaussian",
        "pd_n": 10,
        "vary": false
      }
    }
  }
}
```

**Polydispersity options:**
- `pd_width`: Relative width (0.1 = 10% polydispersity)
- `pd_type`: Distribution shape (`gaussian`, `lognormal`, `schulz`, `rectangle`, `boltzmann`)
- `pd_n`: Number of quadrature points (higher = more accurate, slower)
- `pd_nsigma`: Number of standard deviations to include
- `vary`: Whether to fit the pd_width during optimization

### Example: Fitting with structure factors

Structure factors model inter-particle interactions in concentrated systems. Use `list-structure-factors` to see available options:

- `hardsphere` - Hard sphere (Percus-Yevick closure)
- `hayter_msa` - Hayter-Penfold MSA for charged spheres
- `squarewell` - Square well potential
- `stickyhardsphere` - Sticky hard sphere (Baxter model)

```json
{
  "name": "fitting-with-custom-model",
  "parameters": {
    "input_csv": "simulated_sans_data.csv",
    "model": "sphere",
    "engine": "bumps",
    "method": "amoeba",
    "param_overrides": {
      "radius": { "value": 50, "min": 10, "max": 100, "vary": true },
      "scale": { "value": 0.01, "vary": true },
      "background": { "value": 0.001, "vary": true }
    },
    "structure_factor": "hardsphere",
    "structure_factor_params": {
      "volfraction": { "value": 0.2, "min": 0.0, "max": 0.6, "vary": true },
      "radius_effective": { "value": 50, "min": 10, "max": 100, "vary": true }
    }
  }
}
```

**Structure factor options:**
- `structure_factor`: Name of the structure factor
- `structure_factor_params`: Parameter overrides (volfraction, radius_effective, charge for hayter_msa)
- `radius_effective_mode`: `"unconstrained"` (default) or `"link_radius"` to constrain radius_effective to equal the form factor radius

## Authentication

Set `API_TOKEN` environment variable to enable bearer token authentication:

```bash
API_TOKEN="your-secret-token" sans-pilot
```

Clients must include `Authorization: Bearer <token>` header. If `API_TOKEN` is not set, authentication is disabled.

## Analyses

Analyses are auto-discovered from `src/sans_pilot/analyses/`. Each analysis module exports:
- `ANALYSIS_DESCRIPTION` — shown by `list-analyses`
- `run(**parameters)` — called by `run-analysis`

## Environment Variables

| Variable              | Default                | Description                         |
| --------------------- | ---------------------- | ----------------------------------- |
| `UPLOAD_DIR`          | `/uploads`             | Directory for uploaded data files   |
| `SANS_PILOT_RUNS_DIR` | `/tmp/sans-pilot-runs` | Output directory for analysis runs  |
| `API_TOKEN`           | (none)                 | Bearer token for API authentication |

## Running locally

```bash
cd sans-pilot
python -m venv .venv
source .venv/bin/activate
pip install -e .
sans-pilot
```

## Docker

```bash
docker build -f Dockerfile.dev -t sans-pilot .
docker run -p 8001:8001 -e API_TOKEN="your-token" sans-pilot
```

## Testing

Mount a local data file into `/uploads`:

```bash
docker run -p 8001:8001 \
	-v /path/to/simulated_sans_data.csv:/uploads/simulated_sans_data.csv \
	sans-pilot
```

Run the test script to verify all MCP endpoints:

```bash
cd test
./test_endpoints.sh
```

The script tests all tools against a running server at `http://localhost:8001`. Pass a different URL as argument if needed:

```bash
./test_endpoints.sh http://localhost:9000
```

## Notes

Future improvements planned:
- Run template scripts in a separate container for security and isolation
- Add input parameter validation for all tools
