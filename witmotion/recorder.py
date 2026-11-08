"""CSV recording of samples."""

from __future__ import annotations

import csv
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .sample import Sample

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class Recorder:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._fh = None
        self._writer = None
        self._path: Optional[Path] = None
        self._rows = 0
        self._started: Optional[float] = None

    @property
    def active(self) -> bool:
        return self._writer is not None

    def start(self, name: Optional[str] = None) -> dict:
        with self._lock:
            self._close_locked()
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            label = _SAFE.sub("_", name or "").strip("._")[:60]
            path = self.directory / (f"witmotion_{stamp}{'_' + label if label else ''}.csv")
            self._fh = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(Sample.csv_header())
            self._path = path
            self._rows = 0
            self._started = time.time()
        return self.status()

    def write(self, sample: Sample) -> None:
        if self._writer is None:
            return
        with self._lock:
            if self._writer is None:
                return
            self._writer.writerow(sample.csv_row())
            self._rows += 1
            if self._rows % 50 == 0:
                self._fh.flush()

    def stop(self) -> dict:
        with self._lock:
            info = self._status_locked()
            self._close_locked()
        info["active"] = False
        return info

    def _close_locked(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None
                self._writer = None

    def _status_locked(self) -> dict:
        return {
            "active": self._writer is not None,
            "file": self._path.name if self._path else None,
            "rows": self._rows,
            "started": self._started,
            "duration": (time.time() - self._started) if (self._started and self._writer) else None,
        }

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def list(self) -> List[dict]:
        if not self.directory.is_dir():
            return []
        files = []
        for p in sorted(self.directory.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
            st = p.stat()
            files.append({"name": p.name, "size": st.st_size, "modified": st.st_mtime})
        return files

    def path_for(self, name: str) -> Optional[Path]:
        """Resolve a download name safely inside the recordings directory."""
        if not name or name != Path(name).name or not name.endswith(".csv"):
            return None
        p = (self.directory / name).resolve()
        try:
            p.relative_to(self.directory.resolve())
        except ValueError:
            return None
        return p if p.is_file() else None
