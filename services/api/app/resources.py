"""Tenant/space resource policy validation and resolution."""
from __future__ import annotations

from harness_common import limits as L, models as m
from harness_common.errors import APIError


def _fail(msg: str) -> None:
    raise APIError("CONFLICT", msg)


def validate_tenant_policy(*, cpu: int, memory: int, pids: int,
                           max_cpu: int, max_memory: int, max_pids: int) -> None:
    """Enforce platform hard caps and internal per-space <= total consistency."""
    for name, val, lo, hi, total in (
        ("cpu", cpu, L.MIN_CPU, L.MAX_CPU_PER_SPACE, max_cpu),
        ("memory_bytes", memory, L.MIN_MEMORY_BYTES, L.MAX_MEMORY_PER_SPACE, max_memory),
        ("pids_per_space", pids, L.MIN_PIDS, L.MAX_PIDS_PER_SPACE, max_pids),
    ):
        if not (lo <= val <= hi):
            _fail(f"{name} must be between {lo} and {hi}")
    for name, val, hi in (
        ("max_total_cpu", max_cpu, L.MAX_TOTAL_CPU),
        ("max_total_memory_bytes", max_memory, L.MAX_TOTAL_MEMORY_BYTES),
        ("max_total_pids", max_pids, L.MAX_TOTAL_PIDS),
    ):
        if val < 1 or val > hi:
            _fail(f"{name} must be between 1 and {hi}")
    if cpu > max_cpu or memory > max_memory or pids > max_pids:
        _fail("per-space resource cannot exceed the tenant total quota")


def resolve_space_resources(tenant, *, cpu: int | None, memory: int | None,
                            pids: int | None) -> tuple[int, int, int]:
    """Explicit values override tenant defaults but may not exceed them."""
    resolved = (
        tenant.cpu_per_space if cpu is None else cpu,
        tenant.memory_per_space_bytes if memory is None else memory,
        tenant.pids_per_space if pids is None else pids,
    )
    if resolved[0] < L.MIN_CPU or resolved[0] > tenant.cpu_per_space:
        _fail(f"cpu exceeds tenant limit of {tenant.cpu_per_space}")
    if resolved[1] < L.MIN_MEMORY_BYTES or resolved[1] > tenant.memory_per_space_bytes:
        _fail(f"memory_bytes exceeds tenant limit of {tenant.memory_per_space_bytes}")
    if resolved[2] < L.MIN_PIDS or resolved[2] > tenant.pids_per_space:
        _fail(f"pids_limit exceeds tenant limit of {tenant.pids_per_space}")
    return resolved


def check_tenant_totals_fit(db, tenant) -> None:
    """Reject lowering totals below what is already running."""
    from sqlalchemy import func, select

    totals = db.execute(
        select(
            func.coalesce(func.sum(func.coalesce(m.Workspace.cpu, tenant.cpu_per_space)), 0),
            func.coalesce(func.sum(func.coalesce(m.Workspace.memory_bytes, tenant.memory_per_space_bytes)), 0),
            func.coalesce(func.sum(func.coalesce(m.Workspace.pids_limit, tenant.pids_per_space)), 0),
        ).where(
            m.Workspace.tenant_id == tenant.id,
            m.Workspace.desired_state == m.DESIRED_RUNNING,
        )
    ).one()
    if totals[0] > tenant.max_total_cpu:
        _fail(f"cannot lower max_total_cpu below current usage {totals[0]}")
    if totals[1] > tenant.max_total_memory_bytes:
        _fail(f"cannot lower max_total_memory_bytes below current usage {totals[1]}")
    if totals[2] > tenant.max_total_pids:
        _fail(f"cannot lower max_total_pids below current usage {totals[2]}")


def check_running_totals(db, tenant, workspace) -> None:
    """Deprecated shim: start-quota checks now live in harness_common.quotas."""
    from harness_common.quotas import check_start_quotas

    err = check_start_quotas(db, tenant, workspace)
    if err:
        raise APIError(err[0], err[1])
