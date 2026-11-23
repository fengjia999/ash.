"""Bounded, session-private export diagnostics; never retain backup contents."""
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class BackupProgress:
    owner: str
    started: float = field(default_factory=time.monotonic)
    status: str = "running"
    section: str = "connecting"
    rows: int = 0
    bytes_sent: int = 0
    error: str = ""

    def report(self, section, rows):
        self.section, self.rows = section, rows

    def public(self):
        return {"status": self.status, "section": self.section, "rows": self.rows,
                "bytes_sent": self.bytes_sent, "error": self.error,
                "elapsed_seconds": int(time.monotonic() - self.started)}


_exports: dict[str, BackupProgress] = {}


def start_export(export_id: str, owner: str) -> BackupProgress:
    now = time.monotonic()
    for key, value in list(_exports.items()):
        if now - value.started > 3600:
            del _exports[key]
    previous = _exports.get(export_id)
    if previous and previous.owner != owner:
        raise ValueError("导出标识无效，请重试")
    if previous is None and len(_exports) >= 32:
        del _exports[next(iter(_exports))]
    # Browsers may request an attachment URL again when handing it to their
    # download manager. Track that attempt without sharing mutable state with
    # the earlier response, whose cancellation may arrive afterwards.
    progress = BackupProgress(owner)
    _exports[export_id] = progress
    return progress


def get_export(export_id: str, owner: str):
    progress = _exports.get(export_id)
    if not progress or progress.owner != owner or time.monotonic() - progress.started > 3600:
        return None
    return progress.public()
