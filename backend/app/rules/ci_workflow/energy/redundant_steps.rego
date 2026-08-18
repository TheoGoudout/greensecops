# METADATA
# title: Expensive build repeated across jobs
# description: "A build or publish action runs in three or more jobs. Each job gets a clean runner, so work that produces an artifact is done from scratch every time — the same image layers, the same compilation — when it could be done once and the result shared through an artifact, a registry tag or a job output. Setup work is excluded: checkout, toolchain installation and cache restoration have to repeat per job, because a fresh runner has none of it."
# custom:
#   severity: low
#   severity_weight: 0.6
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         amd64:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/build-push-action@v6
#         arm64:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/build-push-action@v6
#         scan:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: docker/build-push-action@v6
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           outputs:
#             digest: ${{ steps.push.outputs.digest }}
#           steps:
#             - uses: docker/build-push-action@v6
#               id: push
#         scan:
#           needs: build
#           runs-on: ubuntu-latest
#           steps:
#             - run: trivy image --input digest.tar
#     fix: |
#       Build once in a dedicated job and share the result — push the image and pass its digest through a job output, or upload the built artifact and download it in the jobs that consume it. Splitting a genuine build matrix (one job per architecture) is not this; those jobs produce different artifacts.
package greensecops.ci_workflow.energy.redundant_steps

import data.greensecops.lib.workflow as wf
import rego.v1

# Only actions whose repeated execution actually wastes work. The previous
# version flagged any action used in more than two jobs, which made
# `actions/checkout` in three jobs a finding — but every job runs on a fresh
# runner with an empty workspace, so checking out three times is mandatory, not
# redundant. That rule could not be satisfied by any multi-job workflow, and it
# emitted one finding per step occurrence, so a six-job workflow produced six
# identical findings.
#
# Curated rather than inferred: the cost of a false positive here is telling
# someone to restructure a working pipeline, so this errs heavily towards
# silence.
_expensive_actions := {
	"docker/build-push-action",
	"docker/bake-action",
	"gradle/gradle-build-action",
	"gradle/actions/setup-gradle",
	"goreleaser/goreleaser-action",
	"pypa/gh-action-pypi-publish",
}

_jobs_using(action) := {job_name |
	some job_name, job in input.jobs
	some step in job.steps
	wf.action_name(step.uses) == action
}

violations contains violation if {
	some action in _expensive_actions
	jobs_using := _jobs_using(action)
	count(jobs_using) > 2

	violation := {
		"rule": "redundant_steps",
		"severity": "low",
		"category": "energy",
		# Workflow-level: the finding is about the shape of the whole pipeline,
		# not about any one of the steps. One finding per action, not one per
		# occurrence.
		"job": null,
		"message": sprintf(
			"'%v' runs in %v separate jobs (%v). Each runs on a clean runner and redoes the whole build. Build once and share the result through an artifact, a registry tag or a job output.",
			[action, count(jobs_using), concat(", ", sort(jobs_using))],
		),
		"context": action,
		"discriminator": action,
	}
}
