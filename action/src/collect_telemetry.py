#!/usr/bin/env python3
"""GreenSecOps telemetry collector.

Gathers runner hardware specs and resource usage, then POSTs to the
GreenSecOps telemetry ingestion endpoint.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from typing import Any

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_runner_specs() -> dict[str, Any]:
    specs: dict[str, Any] = {
        "os": os.environ.get("RUNNER_OS", platform.system()),
        "arch": os.environ.get("RUNNER_ARCH", platform.machine()),
        "runner_name": os.environ.get("RUNNER_NAME", "unknown"),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
    }

    if HAS_PSUTIL:
        specs["vcpus"] = psutil.cpu_count(logical=True)
        specs["physical_cores"] = psutil.cpu_count(logical=False)
        mem = psutil.virtual_memory()
        specs["ram_total_gb"] = round(mem.total / (1024 ** 3), 2)
        disk = psutil.disk_usage("/")
        specs["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
        specs["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
    else:
        # Fallback via /proc on Linux
        try:
            with open("/proc/cpuinfo") as f:
                specs["vcpus"] = sum(1 for line in f if line.startswith("processor"))
        except OSError:
            pass
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        specs["ram_total_gb"] = round(kb / (1024 ** 2), 2)
                        break
        except OSError:
            pass

    return specs


def get_resource_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {"collected_at": time.time()}

    if not HAS_PSUTIL:
        return metrics

    # Sample CPU usage over 2 seconds
    psutil.cpu_percent(interval=None)
    time.sleep(2)
    metrics["cpu_percent"] = psutil.cpu_percent(interval=None)

    mem = psutil.virtual_memory()
    metrics["ram_used_mb"] = round(mem.used / (1024 ** 2), 1)
    metrics["ram_percent"] = mem.percent

    disk = psutil.disk_usage("/")
    metrics["disk_used_gb"] = round(disk.used / (1024 ** 3), 2)

    # Network I/O counters (cumulative since boot)
    net = psutil.net_io_counters()
    metrics["net_bytes_sent"] = net.bytes_sent
    metrics["net_bytes_recv"] = net.bytes_recv

    # Top 5 processes by CPU
    try:
        procs = []
        for p in sorted(
            psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
            key=lambda x: x.info.get("cpu_percent") or 0,
            reverse=True,
        )[:5]:
            procs.append({
                "name": p.info.get("name"),
                "cpu_percent": p.info.get("cpu_percent"),
                "memory_percent": round(p.info.get("memory_percent") or 0, 2),
            })
        metrics["top_processes"] = procs
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    return metrics


def main() -> int:
    url = os.environ.get("GREENSECOPS_URL", "").rstrip("/")
    token = os.environ.get("GREENSECOPS_TOKEN", "")
    workflow_run_id = os.environ.get("WORKFLOW_RUN_ID") or os.environ.get("GITHUB_RUN_ID", "0")
    repository = os.environ.get("GITHUB_REPOSITORY", "")

    if not url or not token:
        print("::warning::GreenSecOps: GREENSECOPS_URL or GREENSECOPS_TOKEN not set — skipping telemetry")
        return 0

    payload = {
        "workflow_run_id": int(workflow_run_id),
        "repository": repository,
        "branch": os.environ.get("GITHUB_REF", "").removeprefix("refs/heads/"),
        "commit_sha": os.environ.get("GITHUB_SHA", ""),
        "workflow_name": os.environ.get("GITHUB_WORKFLOW", ""),
        "runner_specs": get_runner_specs(),
        "metrics": get_resource_metrics(),
    }

    if not HAS_REQUESTS:
        print("::warning::GreenSecOps: requests library not available — skipping telemetry send")
        print(json.dumps(payload, indent=2))
        return 0

    try:
        response = requests.post(
            f"{url}/api/v1/telemetry/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()
        print(f"::notice::GreenSecOps telemetry sent successfully (status {response.status_code})")
        return 0
    except requests.RequestException as exc:
        print(f"::warning::GreenSecOps telemetry send failed: {exc}")
        return 0  # Non-fatal — don't break the CI


if __name__ == "__main__":
    sys.exit(main())
