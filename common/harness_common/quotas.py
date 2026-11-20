"""Start-quota checks shared by the API (fast fail) and the worker (authoritative).

Both paths must agree: an API check alone is bypassable when the reconciler
enqueues a start on its own (e.g. after a worker restart or observed-state drift).
"""
from __future__ import annotations

from sqlalchemy import func, select

from .models import DESIRED_RUNNING, Workspace


def check_start_quotas(db, tenant, workspace) -> tuple[str, str] | None:
    """Return (error_code, message) if starting would breach tenant quotas.

    The calling layer decides how to surface it (APIError / RuntimeError).
    `workspace.id` is excluded so an idempotent re-start counts only other spaces.
    """
    running = db.execute(
        select(func.count()).select_from(Workspace).where(
            Workspace.tenant_id == tenant.id,
            Workspace.id != workspace.id,
            Workspace.desired_state == DESIRED_RUNNING,
        )
    ).scalar_one()
    if running >= tenant.max_running:
        return "RATE_LIMITED", "Running workspace quota exceeded"

    totals = db.execute(
        select(
            func.coalesce(func.sum(func.coalesce(Workspace.cpu, tenant.cpu_per_space)), 0),
            func.coalesce(func.sum(func.coalesce(Workspace.memory_bytes, tenant.memory_per_space_bytes)), 0),
            func.coalesce(func.sum(func.coalesce(Workspace.pids_limit, tenant.pids_per_space)), 0),
        ).where(
            Workspace.tenant_id == tenant.id,
            Workspace.id != workspace.id,
            Workspace.desired_state == DESIRED_RUNNING,
        )
    ).one()
    cpu = (workspace.cpu or tenant.cpu_per_space) + (totals[0] or 0)
    memory = (workspace.memory_bytes or tenant.memory_per_space_bytes) + (totals[1] or 0)
    pids = (workspace.pids_limit or tenant.pids_per_space) + (totals[2] or 0)
    if cpu > tenant.max_total_cpu:
        return "CONFLICT", f"running CPU quota exceeded ({cpu} > {tenant.max_total_cpu})"
    if memory > tenant.max_total_memory_bytes:
        return "CONFLICT", f"running memory quota exceeded ({memory} > {tenant.max_total_memory_bytes})"
    if pids > tenant.max_total_pids:
        return "CONFLICT", f"running PIDS quota exceeded ({pids} > {tenant.max_total_pids})"
    return None
