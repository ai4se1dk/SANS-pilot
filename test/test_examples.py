"""Tests for curated examples and explicit reproducible simulations."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import numpy as np
import pytest
from pydantic import ValidationError
from sans_fitter import examples

from sans_pilot import example_tools
from sans_pilot.schemas import SimulateSansDataRequest, SimulateSansPairRequest


def test_example_listing_and_inspection_expose_sans_fitter_records():
  biology = example_tools.list_sans_examples(tag="biology")
  assert biology["count"] >= 1
  assert all("biology" in record["tags"] for record in biology["examples"])

  protein = example_tools.inspect_sans_example("protein")
  assert protein["example"]["known_truth"] is None
  assert protein["example"]["suggested_model"] == "sphere"
  assert protein["data"]["points_total"] > 100

  cylinder = example_tools.inspect_sans_example("cylinder")
  assert cylinder["example"]["known_truth"]["radius"] == pytest.approx(20)
  assert cylinder["example"]["notes"] == examples.get_example("cylinder").notes


def test_simulation_schemas_reject_non_finite_values():
  with pytest.raises(ValidationError, match="finite number"):
    SimulateSansDataRequest.model_validate(
      {
        "source": {
          "kind": "simulation",
          "model": "sphere",
          "seed": 42,
          "noise": float("nan"),
        }
      }
    )

  with pytest.raises(ValidationError, match="finite number"):
    SimulateSansPairRequest.model_validate(
      {
        "source": {"kind": "simulation", "model": "sphere", "seed": 42},
        "background_level": float("inf"),
      }
    )


def test_matched_simulation_pair_is_reproducible_and_grid_aligned():
  first_sample, first_background = examples.simulate_pair(
    "sphere",
    radius=50,
    npoints=20,
    seed=42,
  )
  second_sample, second_background = examples.simulate_pair(
    "sphere",
    radius=50,
    npoints=20,
    seed=42,
  )

  np.testing.assert_allclose(first_sample.x, first_background.x)
  np.testing.assert_allclose(first_sample.y, second_sample.y)
  np.testing.assert_allclose(first_background.y, second_background.y)
  assert cast(Any, first_sample).truth["radius"] == pytest.approx(50)


def test_simulation_tool_attaches_csv_only_when_service_returns_it(
  tmp_path,
  monkeypatch,
):
  plot = tmp_path / "simulated_sans_data.png"
  plot.write_bytes(b"png")

  async def run_inline(worker, *args, **_kwargs):
    return worker(*args)

  monkeypatch.setenv("SANS_PILOT_RUNS_DIR", str(tmp_path))
  monkeypatch.setattr(
    example_tools,
    "create_run_directory",
    lambda _name: tmp_path,
  )
  monkeypatch.setattr(example_tools, "run_cancellable_worker", run_inline)
  monkeypatch.setattr(
    example_tools,
    "_render_single_simulation",
    lambda _request, output_dir: {
      "summary": {
        "analysis": "data_simulation",
        "artifacts": [{"name": plot.name, "mime_type": "image/png"}],
      },
      "artifacts": {plot.name: plot},
    },
  )
  request = SimulateSansDataRequest.model_validate(
    {"source": {"kind": "simulation", "model": "sphere", "seed": 42}}
  )

  response = asyncio.run(example_tools.simulate_sans_data(request))

  assert response.structured_content is not None
  assert response.structured_content["analysis"] == "data_simulation"
  assert response.structured_content["artifacts"][0]["uri"].startswith(
    "sans-pilot://artifact/"
  )
  assert any(item.type == "image" for item in response.content)
