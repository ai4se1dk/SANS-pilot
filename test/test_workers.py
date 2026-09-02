"""Tests for cancellable scientific worker processes."""

from __future__ import annotations

import asyncio
import time

import pytest

from sans_pilot.workers import run_cancellable_worker


def test_cancelling_worker_returns_promptly_and_removes_workspace(tmp_path):
  workspace = tmp_path / "cancelled-run"
  workspace.mkdir()
  (workspace / "partial.txt").write_text("partial", encoding="utf-8")

  async def scenario() -> float:
    task = asyncio.create_task(
      run_cancellable_worker(
        time.sleep,
        30,
        operation_name="test-operation",
        output_dir=workspace,
      )
    )
    await asyncio.sleep(0.25)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
    return time.monotonic() - started

  cancellation_time = asyncio.run(scenario())

  assert cancellation_time < 5
  assert not workspace.exists()


def test_worker_hard_timeout_removes_workspace(tmp_path, monkeypatch):
  workspace = tmp_path / "timed-out-run"
  workspace.mkdir()
  monkeypatch.setenv("SANS_PILOT_TOOL_TIMEOUT_SECONDS", "0.1")

  async def scenario():
    await run_cancellable_worker(
      time.sleep,
      30,
      operation_name="test-timeout",
      output_dir=workspace,
    )

  with pytest.raises(TimeoutError, match="test-timeout exceeded"):
    asyncio.run(scenario())
  assert not workspace.exists()
