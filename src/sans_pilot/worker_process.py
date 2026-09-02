"""Subprocess entry point for cancellable sans-pilot scientific operations."""

from __future__ import annotations

import importlib
import pickle
import sys
import traceback
from pathlib import Path
from typing import Any


def _resolve_callable(module: str, qualname: str) -> Any:
  target: Any = importlib.import_module(module)
  for component in qualname.split("."):
    target = getattr(target, component)
  return target


def main() -> None:
  command_path = Path(sys.argv[1])
  result_path = Path(sys.argv[2])
  try:
    module, qualname, args = pickle.loads(command_path.read_bytes())
    result = _resolve_callable(module, qualname)(*args)
    payload: tuple[str, Any] = ("return", result)
  except BaseException as exc:
    payload = ("error", (exc, traceback.format_exc()))

  try:
    result_path.write_bytes(pickle.dumps(payload))
  except BaseException:
    fallback = (
      "error",
      (
        RuntimeError("Scientific worker returned an unserializable result."),
        traceback.format_exc(),
      ),
    )
    result_path.write_bytes(pickle.dumps(fallback))


if __name__ == "__main__":
  main()
