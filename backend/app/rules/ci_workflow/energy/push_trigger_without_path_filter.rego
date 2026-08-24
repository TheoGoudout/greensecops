# METADATA
# title: Workflow runs on every push with no path filter
# description: A workflow triggers on push or pull_request without a paths filter, so it runs in full for changes that cannot possibly affect it — a README edit rebuilds the container image, a comment fix runs the integration suite. On any repository with more than one component this is the largest avoidable source of CI compute there is, because the waste scales with commit volume rather than with anything about the code. It is also the cheapest to fix, since a paths filter is a few lines and needs no change to the jobs themselves.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         push:
#           branches: [main]
#     good: |
#       on:
#         push:
#           branches: [main]
#           paths:
#             - "backend/**"
#             - ".github/workflows/backend.yml"
#     fix: |
#       Add a paths filter naming what the workflow actually depends on, and include the workflow file itself so a change to it still triggers a run. Where a required status check is involved, use paths-ignore rather than paths — a workflow skipped by a paths filter never reports, and a required check that never reports blocks the merge.
package greensecops.ci_workflow.energy.push_trigger_without_path_filter

import data.greensecops.lib.workflow as wf
import rego.v1

_filtered(event) if input.on[event].paths

_filtered(event) if input.on[event]["paths-ignore"]

# Presence comes from `wf.trigger_names`, which normalises the three shapes
# `on:` can take. The previous version required `is_object(input.on[event])`,
# which meant a bare `on: {push: null}` or `on: [push]` — the *least* filtered
# forms there are, and the ones that literally cannot carry a filter — were
# silently exempt, while `on: {push: {branches: [main]}}` fired. The rule
# reported the more careful workflow and skipped the less careful one.
violations contains violation if {
	some event in ["push", "pull_request"]
	wf.has_trigger(event)
	not _filtered(event)

	violation := {
		"rule": "push_trigger_without_path_filter",
		"severity": "low",
		"category": "energy",
		"job": null,
		"message": sprintf("Workflow runs on every %v with no paths filter, so a change that cannot affect it still runs it in full.", [event]),
		"context": event,
		"discriminator": event,
	}
}
