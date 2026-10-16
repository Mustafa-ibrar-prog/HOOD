"""Job persistence (one JSON file per job) and a background worker pool."""
from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from .config import settings
from .models import Job, JobStatus
from .storage import storage

log = logging.getLogger(__name__)


class JobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._cancel: set[str] = set()
        self._load()

    def _load(self) -> None:
        for f in self.root.glob("*/job.json"):
            try:
                job = Job.model_validate_json(f.read_text())
            except Exception as e:  # corrupt file: skip rather than crash startup
                log.warning("skipping unreadable job file %s: %s", f, e)
                continue
            if job.status in {JobStatus.queued, JobStatus.running}:
                job.status = JobStatus.failed
                job.error = "The server restarted while this job was running. Please retry."
                job.error_code = "interrupted"
            for c in job.clips:
                if c.status in {"pending", "rendering"}:
                    c.status = "failed"
                    c.error = "Interrupted by a server restart; click regenerate."
            self._jobs[job.id] = job

    def dir(self, job_id: str) -> Path:
        if not job_id.isalnum():
            raise ValueError("bad job id")
        return self.root / job_id

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self.dir(job.id).mkdir(parents=True, exist_ok=True)
            self.save(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def save(self, job: Job) -> None:
        with self._lock:
            job.updated_at = time.time()
            d = self.dir(job.id)
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "job.json.tmp"
            tmp.write_text(job.model_dump_json(indent=1))
            tmp.replace(d / "job.json")

    def update(self, job_id: str, fn: Callable[[Job], None]) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            fn(job)
            self.save(job)
            return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            self._cancel.add(job_id)
        shutil.rmtree(self.dir(job_id), ignore_errors=True)
        try:
            storage.delete_job(job_id)
        except Exception as e:
            log.warning("storage cleanup failed for %s: %s", job_id, e)
        return job is not None

    def request_cancel(self, job_id: str) -> None:
        with self._lock:
            self._cancel.add(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel

    def cleanup(self, older_than_hours: float) -> list[str]:
        cutoff = time.time() - older_than_hours * 3600
        removed = []
        for job in self.list():
            if job.updated_at < cutoff and job.status not in {JobStatus.queued, JobStatus.running}:
                self.delete(job.id)
                removed.append(job.id)
        # Orphaned directories with no job.json
        for d in self.root.iterdir():
            if d.is_dir() and not (d / "job.json").exists() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        return removed

    def disk_usage_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


store = JobStore(settings.jobs_dir)
executor = ThreadPoolExecutor(max_workers=max(settings.worker_threads, 1), thread_name_prefix="clipforge")
