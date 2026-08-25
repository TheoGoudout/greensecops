"""Scan lifecycle state machine (``python-statemachine``).

States mirror ``ScanStatus``. Every engine's scan runs this graph:
``WorkflowScan``, ``TerraformScan``, ``DockerScan`` and ``CloudScan``. The CI
engine used to have its own identical copy called ``ScanMachine`` — same
five states, same six edges, differing only in that it named the success edge
``opa_succeeded`` and the empty case ``no_workflows_found``. Both machines were
tested separately, and a fix to one would not have reached the other.

The graph is connected and single-initial (a library requirement), which also
closed the old gaps in the CI copy: the never-persisted ``pending`` and
``skipped`` values are absent, and the empty case is reached by an explicit edge
rather than being a disconnected second initial state.

Behaviour lives in ``services/scan_runner.py`` (Terraform and Docker),
``workers/tasks/static_analysis.py`` (CI), ``workers/tasks/cloud_scan.py``, and
the stuck-row sweeper in ``workers/tasks/maintenance.py``.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import ScanStatus, SSESignal


class ScanMachine(StateMachine):
    state_field = "status"

    queued = State(initial=True, value=ScanStatus.queued)
    running = State(value=ScanStatus.running)
    completed = State(value=ScanStatus.completed, final=True)
    # Not ``final``: ``retry`` re-queues a (transient) failure in place,
    # mirroring ScanMachine.
    failed = State(value=ScanStatus.failed)
    no_targets = State(value=ScanStatus.no_targets, final=True)

    # Inputs (events)
    started = queued.to(running)  # worker begins fetch/collect + evaluation
    succeeded = running.to(completed)
    scan_failed = running.to(failed)
    no_targets_found = running.to(no_targets)
    # Stuck-row sweeper: a row that never got picked up (``queued``) or whose
    # worker died mid-scan (``running``) is declared failed after the shared
    # staleness cutoff.
    swept = queued.to(failed) | running.to(failed)
    # In-place recovery for a failed scan: re-queue the same row so the worker
    # re-runs it. Whether that is worthwhile is carried by ``failure_kind``.
    retry = failed.to(queued)

    # The CI engine publishes these; the other three engines have no live
    # scan-status stream yet, so for them a transition simply fires nothing.
    # Declared here rather than per-engine because the signal describes the
    # transition, and nothing dispatches through ``output_for`` for scans — the
    # workers publish explicitly (see ``services/events/schemas.py``).
    outputs: dict[str, SSESignal | None] = {
        "started": SSESignal.analysis_started,
        "succeeded": SSESignal.analysis_completed,
        "scan_failed": SSESignal.analysis_failed,
        "no_targets_found": SSESignal.analysis_no_workflows,
        "swept": SSESignal.analysis_failed,
        "retry": SSESignal.analysis_queued,
    }
