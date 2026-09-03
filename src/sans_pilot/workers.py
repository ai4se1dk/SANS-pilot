"""Cancellable subprocess isolation for synchronous scientific tool calls."""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pickle
import shutil
import signal
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio

logger = logging.getLogger(__name__)
_worker_limiter: anyio.CapacityLimiter | None = None


def _positive_int_environment(name: str, default: int) -> int:
  try:
    return max(1, int(os.environ.get(name, str(default))))
  except ValueError:
    return default


def _nonnegative_float_environment(name: str, default: float) -> float:
  try:
    return max(0.0, float(os.environ.get(name, str(default))))
  except ValueError:
    return default


def get_worker_limiter() -> anyio.CapacityLimiter:
  """Return the process-wide limiter for concurrent scientific workers."""
  global _worker_limiter
  if _worker_limiter is None:
    _worker_limiter = anyio.CapacityLimiter(
      _positive_int_environment("SANS_PILOT_MAX_WORKERS", 2)
    )
  return _worker_limiter


def _remove_cancelled_workspace(output_dir: Path | None) -> None:
  if output_dir is None:
    return
  try:
    shutil.rmtree(output_dir, ignore_errors=True)
  except OSError:
    logger.warning("Failed to remove cancelled workspace %s", output_dir)


def _callable_reference(worker: Callable[..., Any]) -> tuple[str, str]:
  module = getattr(worker, "__module__", None)
  qualname = getattr(worker, "__qualname__", None)
  if not module or not qualname or "<locals>" in qualname:
    raise TypeError("Scientific worker must be an importable top-level callable.")
  # Resolve it now so configuration errors fail before a subprocess is started.
  target: Any = importlib.import_module(module)
  for component in qualname.split("."):
    target = getattr(target, component)
  if target is not worker:
    raise TypeError(f"Scientific worker {module}.{qualname} is not import-stable.")
  return module, qualname


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
  if process.returncode is not None:
    return
  try:
    if os.name == "posix":
      os.killpg(process.pid, signal.SIGTERM)
    else:
      process.terminate()
  except ProcessLookupError:
    return
  try:
    await asyncio.wait_for(process.wait(), timeout=2)
    return
  except TimeoutError:
    pass
  try:
    if os.name == "posix":
      os.killpg(process.pid, signal.SIGKILL)
    else:
      process.kill()
  except ProcessLookupError:
    return
  await process.wait()


async def run_cancellable_worker(
  worker: Callable[..., Any],
  *args: Any,
  operation_name: str,
  output_dir: str | Path | None = None,
) -> Any:
  """Run an importable synchronous callable in a killable subprocess.

  Each operation receives a fresh Python interpreter and process group. If the
  MCP request is cancelled, the complete group is terminated so nested workers
  and renderers do not continue consuming CPU. A hard timeout provides the same
  cleanup when a client fails to propagate cancellation.
  """
  module, qualname = _callable_reference(worker)
  workspace = Path(output_dir) if output_dir is not None else None
  timeout_seconds = _nonnegative_float_environment(
    "SANS_PILOT_TOOL_TIMEOUT_SECONDS", 1800.0
  )

  async with get_worker_limiter():
    with tempfile.TemporaryDirectory(prefix="sans-pilot-worker-") as temporary:
      command_path = Path(temporary) / "command.pkl"
      result_path = Path(temporary) / "result.pkl"
      command_path.write_bytes(pickle.dumps((module, qualname, args)))

      process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "sans_pilot.worker_process",
        str(command_path),
        str(result_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name == "posix"),
      )
      try:
        communicate = process.communicate()
        if timeout_seconds == 0:
          _stdout, stderr = await communicate
        else:
          _stdout, stderr = await asyncio.wait_for(communicate, timeout=timeout_seconds)
      except asyncio.CancelledError:
        logger.info("Cancelled sans-pilot worker for %s", operation_name)
        await _terminate_process(process)
        _remove_cancelled_workspace(workspace)
        raise
      except TimeoutError as exc:
        logger.warning(
          "Timed out sans-pilot worker for %s after %.1f seconds",
          operation_name,
          timeout_seconds,
        )
        await _terminate_process(process)
        _remove_cancelled_workspace(workspace)
        raise TimeoutError(
          f"{operation_name} exceeded the server execution timeout of "
          f"{timeout_seconds:g} seconds."
        ) from exc

      if not result_path.is_file():
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
          f"{operation_name} worker exited with code {process.returncode}"
          + (f": {detail}" if detail else ".")
        )

      status, payload = pickle.loads(result_path.read_bytes())
      if status == "error":
        error, traceback_text = payload
        if isinstance(error, BaseException):
          add_note = getattr(error, "add_note", None)
          if callable(add_note):
            add_note(f"Worker traceback:\n{traceback_text}")
          raise error
        raise RuntimeError(f"{operation_name} failed: {error}\n{traceback_text}")
      return payload
