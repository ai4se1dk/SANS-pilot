"""Tests for user-scoped uploaded-file resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sans_pilot.files import resolve_uploaded_path


def test_resolve_uploaded_path_accepts_current_user_file(tmp_path, monkeypatch):
  monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
  user_dir = tmp_path / "user-1"
  user_dir.mkdir()
  uploaded = user_dir / "sample.csv"
  uploaded.write_text("Q,I,dI\n0.1,1,0.1\n", encoding="utf-8")

  assert resolve_uploaded_path("sample.csv", user_id="user-1") == uploaded
  assert resolve_uploaded_path(str(uploaded), user_id="user-1") == uploaded


def test_resolve_uploaded_path_rejects_other_user_absolute_path(tmp_path, monkeypatch):
  monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
  own_dir = tmp_path / "user-1"
  other_dir = tmp_path / "user-2"
  own_dir.mkdir()
  other_dir.mkdir()
  other_file = other_dir / "sample.csv"
  other_file.write_text("data", encoding="utf-8")

  with pytest.raises(ValueError, match="current user's upload directory"):
    resolve_uploaded_path(str(other_file), user_id="user-1")


def test_resolve_uploaded_path_rejects_parent_traversal(tmp_path, monkeypatch):
  monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
  user_dir = tmp_path / "user-1"
  user_dir.mkdir()
  outside = tmp_path / "outside.csv"
  outside.write_text("data", encoding="utf-8")

  with pytest.raises(ValueError, match="cannot leave"):
    resolve_uploaded_path(Path("../outside.csv").as_posix(), user_id="user-1")
