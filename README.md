# sans-pilot

MCP server for SANS (Small-Angle Neutron Scattering) data analysis.

## Tools

| Tool                     | Description                                                     |
| ------------------------ | --------------------------------------------------------------- |
| `describe-possibilities` | Describe server capabilities                                    |
| `list-uploaded-files`    | List uploaded data files (optional: filter by extension, limit) |
| `list-templates`         | List available analysis templates with parameters               |
| `run-template`           | Run analysis template, returns fit results and plot             |

## Templates

Templates are auto-discovered from `src/sans_pilot/templates/`. Each template exports:
- `TEMPLATE_DESCRIPTION` — shown by `list-templates`
- `run(**parameters)` — called by `run-template`

## Environment Variables

| Variable              | Default                | Description                        |
| --------------------- | ---------------------- | ---------------------------------- |
| `UPLOAD_DIR`          | `/uploads`             | Directory for uploaded data files  |
| `SANS_PILOT_RUNS_DIR` | `/tmp/sans-pilot-runs` | Output directory for analysis runs |

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
docker run -p 8001:8001 sans-pilot
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
