"""Terraform/cloud scan lifecycle state machine (``python-statemachine``).

States mirror ``ScanStatus``. Shared by ``TerraformScan.status``,
``DockerScan.status`` and ``CloudScan.status`` — the lifecycles are identical
(fetch/collect, evaluate, persist findings, grade), only the source of the
input differs (fetched .tf files, Dockerfiles, or a live AWS API sweep).
Mirrors ``AnalysisMachine``, the equivalent lifecycle for the CI-workflow
engine.

Behaviour lives in ``workers/tasks/terraform_analysis.py``,
``docker_analysis.py`` and ``cloud_scan.py``, plus the stuck-row sweeper in
``maintenance.py``; this machine is the graph they advance against.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import ScanStatus


class ScanMachine(StateMachine):
    state_field = "status"

    queued = State(initial=True, value=ScanStatus.queued)
    running = State(value=ScanStatus.running)
    completed = State(value=ScanStatus.completed, final=True)
    # Not ``final``: ``retry`` re-queues a (transient) failure in place,
    # mirroring AnalysisMachine.
    failed = State(value=ScanStatus.failed)
    no_targets = State(value=ScanStatus.no_targets, final=True)

    # Inputs (events)
    started = queued.to(running)  # worker begins fetch/collect + evaluation
    succeeded = running.to(completed)
    scan_failed = running.to(failed)
    no_targets_found = running.to(no_targets)
    # Stuck-row sweeper (mirrors AnalysisMachine.swept): a row that never got
    # picked up (``queued``) or whose worker died mid-scan (``running``) is
    # declared failed after the shared staleness cutoff.
    swept = queued.to(failed) | running.to(failed)
    retry = failed.to(queued)

    # No SSE wiring yet — lands with the phase that adds live scan-status
    # updates to the frontend (mirrors IssueMachine, which also declares the
    # graph ahead of any signal consumer).
    outputs: dict[str, None] = {
        "started": None,
        "succeeded": None,
        "scan_failed": None,
        "no_targets_found": None,
        "swept": None,
        "retry": None,
    }
