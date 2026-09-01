"""Tests for the strict sans-fitter 0.3 dataset contract."""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
from pydantic import ValidationError
from sasdata.dataloader.data_info import Data1D

from sans_pilot import datasets
from sans_pilot.schemas import (
  DataOperation,
  DatasetPipeline,
  ExampleDataSource,
  SimulationDataSource,
  UploadDataSource,
)


def _write_sans_csv(path: Path, *, intensity: float = 1.0) -> None:
  rows = ["Q,I,dI"]
  rows.extend(f"{q / 100:.2f},{intensity},0.1" for q in range(1, 11))
  path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _data(intensity: float = 1.0) -> Data1D:
  q = np.linspace(0.01, 0.1, 10)
  data = Data1D(
    x=q,
    y=np.full(q.size, intensity),
    dy=np.full(q.size, 0.1),
  )
  dynamic = cast(Any, data)
  dynamic.qmin = float(q.min())
  dynamic.qmax = float(q.max())
  dynamic.mask = np.zeros(q.size, dtype=bool)
  return data


def test_pipeline_rejects_unknown_and_legacy_fields():
  with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
    DatasetPipeline.model_validate(
      {
        "primary": {"kind": "upload", "file": "sample.csv"},
        "input_csv": "legacy.csv",
      }
    )


def test_pipeline_validates_operations_and_q_range():
  with pytest.raises(ValidationError, match="exactly one"):
    DataOperation(operation="subtract")

  with pytest.raises(ValidationError, match="unknown auxiliary"):
    DatasetPipeline(
      primary=UploadDataSource(kind="upload", file="sample.csv"),
      operations=[DataOperation(operation="subtract", operand="background")],
    )


def test_simulation_schema_allows_sans_fitter_defaults():
  source = SimulationDataSource.model_validate(
    {"kind": "simulation", "model": "sphere"}
  )
  assert source.seed is None


def test_supported_format_registry_covers_curated_1d_extensions():
  assert {
    "csv",
    "txt",
    "asc",
    "abs",
    "cor",
    "dat",
    "xml",
    "h5",
    "hdf",
    "hdf5",
    "nxs",
    "pdh",
  } <= datasets.SUPPORTED_1D_EXTENSIONS
  assert "ses" not in datasets.SUPPORTED_1D_EXTENSIONS
  assert "sans" not in datasets.SUPPORTED_1D_EXTENSIONS


@pytest.mark.parametrize(
  ("extension", "source_name"),
  [
    ("abs", "AUSANS_run3_2_no_buffer.ABS"),
    ("cor", "AUSANS_run3_2_no_buffer.ABS"),
    ("csv", "Alumina_usaxs.csv"),
    ("txt", "98929.txt"),
    ("asc", "98929.txt"),
    ("dat", "beam profile.DAT"),
    ("xml", "33837rear_1D_1.75_16.5_CanSAS1D.xml"),
    ("h5", "Lew_Sa3_DSM_QinA.h5"),
    ("hdf", "FK403_0006_Nika.hdf"),
    ("hdf5", "Lew_Sa3_DSM_QinA.h5"),
    ("nxs", "Lew_Sa3_DSM_QinA.h5"),
    ("pdh", "saxess_example.pdh"),
  ],
)
def test_every_advertised_extension_loads_representative_1d_data(
  tmp_path,
  monkeypatch,
  extension,
  source_name,
):
  uploads = tmp_path / "uploads"
  uploads.mkdir()
  source = files("sasdata").joinpath("example_data", "1d_data", source_name)
  destination = uploads / f"sample.{extension}"
  shutil.copyfile(str(source), destination)
  monkeypatch.setenv("UPLOAD_DIR", str(uploads))

  prepared = datasets.prepare_dataset(
    DatasetPipeline(
      primary=UploadDataSource(kind="upload", file=destination.name),
    ),
    user_id=None,
  )

  assert len(prepared.data.x) > 0
  assert prepared.source["extension"] == extension
  assert prepared.source["data_type"] == "Data1D"


def test_upload_pipeline_is_user_scoped_and_applies_q_range(tmp_path):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  _write_sans_csv(user_dir / "sample.csv")

  pipeline = DatasetPipeline(
    primary=UploadDataSource(kind="upload", file="sample.csv"),
    q_min=0.03,
    q_max=0.08,
  )
  with pytest.MonkeyPatch.context() as monkeypatch:
    monkeypatch.setenv("UPLOAD_DIR", str(uploads))
    prepared = datasets.prepare_dataset(pipeline, user_id="user-1")

  assert prepared.source["kind"] == "upload"
  assert prepared.source["format"] == "columnar_text"
  assert prepared.data.qmin == pytest.approx(0.03)
  assert prepared.data.qmax == pytest.approx(0.08)
  summary = datasets.inspect_data(prepared.data)
  assert summary["points_active"] == 6
  assert summary["requested_q_range"] == {"min": 0.03, "max": 0.08}
  assert summary["actual_q_range"] == {"min": 0.03, "max": 0.08}
  assert prepared.preprocessing == [
    {"operation": "select_q_range", "q_min": 0.03, "q_max": 0.08}
  ]


def test_inspection_ranges_use_only_active_points():
  data = _data()
  dynamic = cast(Any, data)
  dynamic.qmin = 0.025
  dynamic.qmax = 0.085

  summary = datasets.inspect_data(data)

  assert summary["points_active"] == 6
  assert summary["requested_q_range"] == {"min": 0.025, "max": 0.085}
  assert summary["actual_q_range"] == pytest.approx({"min": 0.03, "max": 0.08})
  assert summary["intensity_range"] == {"min": 1.0, "max": 1.0}


def test_repository_resolution_csv_aliases_load_with_di_and_dq(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  uploads.mkdir()
  source = (
    Path(__file__).parents[2]
    / "SANS-fitter"
    / "simulated_sans_data_with_resolution.csv"
  )
  destination = uploads / "resolution.csv"
  shutil.copyfile(source, destination)
  monkeypatch.setenv("UPLOAD_DIR", str(uploads))

  prepared = datasets.prepare_dataset(
    DatasetPipeline(primary=UploadDataSource(kind="upload", file=destination.name)),
    user_id=None,
  )
  summary = datasets.inspect_data(prepared.data)

  assert summary["points_total"] == 200
  assert summary["has_intensity_errors"] is True
  assert summary["resolution_type"] == "pinhole"


def test_pipeline_applies_ordered_dataset_and_scalar_operations(tmp_path):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  _write_sans_csv(user_dir / "sample.csv", intensity=10)
  _write_sans_csv(user_dir / "background.csv", intensity=2)

  pipeline = DatasetPipeline(
    primary=UploadDataSource(kind="upload", file="sample.csv"),
    auxiliary={"background": UploadDataSource(kind="upload", file="background.csv")},
    operations=[
      DataOperation(operation="subtract", operand="background"),
      DataOperation(operation="multiply", scalar=0.5),
    ],
  )
  with pytest.MonkeyPatch.context() as monkeypatch:
    monkeypatch.setenv("UPLOAD_DIR", str(uploads))
    prepared = datasets.prepare_dataset(pipeline, user_id="user-1")

  np.testing.assert_allclose(prepared.data.y, 4)
  assert prepared.preprocessing == [
    {"operation": "subtract", "operand": "background"},
    {"operation": "multiply", "scalar": 0.5},
  ]
  assert prepared.auxiliary_sources["background"]["file_name"] == "background.csv"


def test_example_and_simulation_sources_are_fit_ready_and_provenanced():
  example = datasets.prepare_dataset(
    DatasetPipeline(primary=ExampleDataSource(kind="example", name="protein")),
    user_id=None,
  )
  assert example.source["kind"] == "example"
  assert datasets.inspect_data(example.data)["points_total"] > 100

  simulation_source = SimulationDataSource(
    kind="simulation",
    model="sphere",
    parameters={"radius": 50},
    points=25,
    seed=42,
  )
  first = datasets.prepare_dataset(
    DatasetPipeline(primary=simulation_source),
    user_id=None,
  )
  second = datasets.prepare_dataset(
    DatasetPipeline(primary=simulation_source),
    user_id=None,
  )
  np.testing.assert_allclose(first.data.y, second.data.y)
  assert first.source["truth"]["radius"] == pytest.approx(50)


def test_upload_requires_selection_for_multiple_datasets(
  tmp_path,
  monkeypatch,
):
  uploads = tmp_path / "uploads"
  user_dir = uploads / "user-1"
  user_dir.mkdir(parents=True)
  input_file = user_dir / "container.h5"
  input_file.write_bytes(b"placeholder")

  class MultiLoader:
    def load(self, _path):
      return [_data(1), _data(2)]

  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  monkeypatch.setattr(datasets, "Loader", MultiLoader)

  with pytest.raises(ValueError, match="contains 2 datasets"):
    datasets.prepare_dataset(
      DatasetPipeline(
        primary=UploadDataSource(kind="upload", file="container.h5"),
      ),
      user_id="user-1",
    )

  selected = datasets.prepare_dataset(
    DatasetPipeline(
      primary=UploadDataSource(
        kind="upload",
        file="container.h5",
        dataset_index=1,
      ),
    ),
    user_id="user-1",
  )
  np.testing.assert_allclose(selected.data.y, 2)


def test_concurrent_upload_loading_is_stable(tmp_path, monkeypatch):
  uploads = tmp_path / "uploads"
  uploads.mkdir()
  _write_sans_csv(uploads / "sample.csv")
  monkeypatch.setenv("UPLOAD_DIR", str(uploads))
  pipeline = DatasetPipeline(primary=UploadDataSource(kind="upload", file="sample.csv"))

  def load_once(_index: int) -> tuple[int, float, tuple[str, ...]]:
    prepared = datasets.prepare_dataset(pipeline, user_id=None)
    return (
      len(prepared.data.x),
      float(np.sum(prepared.data.y)),
      tuple(prepared.warnings),
    )

  with ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(load_once, range(40)))

  assert results == [(10, 10.0, ())] * 40


def test_processed_csv_contains_only_active_valid_points(tmp_path):
  data = _data()
  dynamic = cast(Any, data)
  dynamic.qmin = 0.03
  dynamic.qmax = 0.08
  dynamic.mask[4] = True

  output_path = datasets.save_processed_data(data, tmp_path / "processed.csv")
  loaded = datasets.data_ops.load(str(output_path))

  assert len(loaded.x) == 5
  assert np.min(loaded.x) >= 0.03
  assert np.max(loaded.x) <= 0.08
