"""Keep the workflow-analysis tests off the network.

``static_analysis`` resolves a branch to its head commit before reading any
file, so that a stored snapshot records which commit it came from and a delayed
run cannot write an older commit over a newer one. Every test in this package
already patches the *listing* seam (``_fetch_workflow_files``); without this
fixture they would each also have to patch the *resolve* seam or make a real,
failing GitHub call for a repository that does not exist.

Patching it once here keeps those tests about what they are actually asserting.
A test that cares about the resolved SHA — provenance, or the write-ordering
guard — patches ``_resolve_ref_sha`` itself, and the inner patch wins.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest

# Deterministic, and shaped like a real commit SHA so anything that slices or
# validates it behaves the way it would in production.
FAKE_HEAD_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _stub_ref_resolution() -> Generator[None, None, None]:
    with patch(
        "app.workers.tasks.static_analysis._resolve_ref_sha",
        return_value=FAKE_HEAD_SHA,
    ):
        yield
