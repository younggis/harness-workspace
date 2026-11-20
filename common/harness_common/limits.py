"""Platform-wide hard caps for tenant-declared container resources.

These are intentionally code constants (not tenant-editable): a tenant must never
be able to declare a container larger than the host can satisfy. Docker maps them
to nano_cpus / mem_limit / pids_limit in DockerRuntimeDriver.
"""
from __future__ import annotations

GIB = 1024 ** 3
MIB = 1024 ** 2

MIN_CPU = 1
MAX_CPU_PER_SPACE = 32
MIN_MEMORY_BYTES = 256 * MIB
MAX_MEMORY_PER_SPACE = 64 * GIB
MIN_PIDS = 64
MAX_PIDS_PER_SPACE = 4096

MAX_TOTAL_CPU = 256
MAX_TOTAL_MEMORY_BYTES = 512 * GIB
MAX_TOTAL_PIDS = 65536

# Applied on tenant creation and used to backfill existing rows in migration 0007.
DEFAULT_CPU_PER_SPACE = 1
DEFAULT_MEMORY_PER_SPACE = GIB
DEFAULT_PIDS_PER_SPACE = 256
DEFAULT_MAX_TOTAL_CPU = 4
DEFAULT_MAX_TOTAL_MEMORY = 4 * GIB
DEFAULT_MAX_TOTAL_PIDS = 1024
