"""Checkpoints for resumable runs, and a response cache keyed by model, prompt and question."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class Checkpoint:
    def __init__(self, results_dir: Path, run_id: str) -> None:
        self.path = results_dir / f"{run_id}.checkpoint.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        done: dict[str, dict[str, Any]] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                done[str(record["id"])] = record
        return done

    def append(self, record: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")


class ResponseCache:
    def __init__(self, directory: Path, model: str, prompt_version: str) -> None:
        self._dir = directory
        self._model = model
        self._prompt_version = prompt_version

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(
            json.dumps([self._model, self._prompt_version, key]).encode("utf-8")
        ).hexdigest()
        return self._dir / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(json.dumps(value, default=str), encoding="utf-8")
