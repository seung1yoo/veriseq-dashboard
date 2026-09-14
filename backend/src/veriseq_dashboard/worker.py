from __future__ import annotations

import socket
import time

from .config import get_settings
from .db import SessionLocal
from .jobs import claim_next_job, process_job, recover_interrupted_jobs


def run_once(worker_id: str | None = None) -> bool:
    settings = get_settings()
    worker_id = worker_id or socket.gethostname()
    with SessionLocal() as session:
        recover_interrupted_jobs(session, settings.worker_lease_seconds)
        job = claim_next_job(session, worker_id)
        if job is None:
            return False
        try:
            process_job(session, job.id, settings.source_root)
        except Exception:  # noqa: BLE001 - process_job already persists the failure safely.
            return True
    return True


def run() -> None:
    settings = get_settings()
    while True:
        worked = run_once()
        if not worked:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run()
