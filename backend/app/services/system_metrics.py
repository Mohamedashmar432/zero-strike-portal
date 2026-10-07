"""CPU, memory and disk load of *this* backend instance, for the admin Operations page.

Inside a container, psutil's machine-wide numbers describe the host, not the container: a 2 GB
container on a 64 GB host would read as 3% memory used right up to the moment the OOM killer fires.
So the cgroup v2 files the container is actually limited by come first, and psutil's host view is
only the fallback (a developer machine, where there is no container).
"""

import os
import shutil
import time
from pathlib import Path

import psutil

CGROUP = Path("/sys/fs/cgroup")
# CPU is a rate, so it needs two readings. Short enough to sit in a request, long enough to not be noise.
SAMPLE_SECONDS = 0.25


def _read(name: str) -> str | None:
    try:
        return (CGROUP / name).read_text().strip()
    except OSError:
        return None


def _cgroup_cpu_usage_usec() -> int | None:
    stat = _read("cpu.stat")
    if not stat:
        return None
    for line in stat.splitlines():
        key, _, value = line.partition(" ")
        if key == "usage_usec":
            return int(value)
    return None


def _cgroup_cpu_limit_cores() -> float | None:
    """`cpu.max` is "<quota> <period>", or "max <period>" when unlimited."""
    raw = _read("cpu.max")
    if not raw:
        return None
    quota, _, period = raw.partition(" ")
    if quota == "max" or not period:
        return None
    return int(quota) / int(period)


def _cgroup_memory() -> tuple[int, int | None] | None:
    current = _read("memory.current")
    if current is None:
        return None
    limit = _read("memory.max")
    return int(current), (None if limit in (None, "max") else int(limit))


def _subprocess_rss() -> tuple[int, int, int]:
    """(backend RSS, subprocess count, subprocess RSS) — the subprocesses are git and the scanner."""
    me = psutil.Process()
    rss = me.memory_info().rss
    children = 0
    child_rss = 0
    for child in me.children(recursive=True):
        try:
            child_rss += child.memory_info().rss
            children += 1
        except psutil.Error:  # exited between listing and reading
            pass
    return rss, children, child_rss


def sample(disk_path: str) -> dict:
    """Blocking (sleeps SAMPLE_SECONDS) — call through asyncio.to_thread."""
    host_cores = os.cpu_count() or 1
    cg_mem = _cgroup_memory()
    cg_cpu_start = _cgroup_cpu_usage_usec()

    if cg_cpu_start is not None and cg_mem is not None:
        source = "cgroup"
        t0 = time.monotonic()
        time.sleep(SAMPLE_SECONDS)
        used_usec = (_cgroup_cpu_usage_usec() or cg_cpu_start) - cg_cpu_start
        elapsed_usec = (time.monotonic() - t0) * 1_000_000
        cores = _cgroup_cpu_limit_cores() or host_cores
        cpu_percent = 100 * used_usec / elapsed_usec / cores
        mem_used, mem_limit = cg_mem
        # No memory limit set on the container: the host's RAM is the real ceiling.
        mem_limit = mem_limit or psutil.virtual_memory().total
    else:
        source = "host"
        cpu_percent = psutil.cpu_percent(interval=SAMPLE_SECONDS)
        cores = host_cores
        vm = psutil.virtual_memory()
        mem_used, mem_limit = vm.total - vm.available, vm.total

    rss, children, child_rss = _subprocess_rss()
    try:
        disk = shutil.disk_usage(disk_path)
        disk_used, disk_total = disk.used, disk.total
    except OSError:
        disk_used = disk_total = None

    return {
        "source": source,
        "cpu_percent": round(min(max(cpu_percent, 0.0), 100.0), 1),
        "cpu_cores": round(cores, 2),
        "memory_used_bytes": mem_used,
        "memory_limit_bytes": mem_limit,
        "memory_percent": round(100 * mem_used / mem_limit, 1) if mem_limit else None,
        "process_rss_bytes": rss,
        "subprocess_count": children,
        "subprocess_rss_bytes": child_rss,
        "disk_used_bytes": disk_used,
        "disk_total_bytes": disk_total,
    }
