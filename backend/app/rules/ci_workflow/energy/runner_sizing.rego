# METADATA
# title: Large runner with no work that needs one
# description: "A job requests a GPU, a larger GitHub-hosted runner or a self-hosted size label, but nothing in it is compute-intensive — no build, compile, test-suite, container image or training step. A larger runner draws more power and costs more per minute for every run, and a job that spends that on installing a linter and reading a file is paying for capacity it never uses. The check errs heavily towards silence: any step that looks like real work, in a `run:` script or in a known heavy action, clears the job."
# custom:
#   severity: medium
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         check:
#           runs-on: ubuntu-latest-16-cores
#           steps:
#             - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
#             - run: yamllint .github/workflows
#     good: |
#       jobs:
#         check:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
#             - run: yamllint .github/workflows
#     fix: |
#       Move the job to the default runner. Where a workflow genuinely needs a large runner for one job, keep it on that job — `runs-on` is per job, so the heavy one can have the capacity while the checks around it stay small.
package greensecops.ci_workflow.energy.runner_sizing

import data.greensecops.lib.workflow as wf
import rego.v1

# Absorbed `large_runner_justification`, which asked the same question with a
# different label list and a different threshold, so a job on a big runner
# doing nothing could produce two findings — one `energy: high`, one
# `energy: medium` — for one decision. This keeps the medium: it is advice
# about capacity, not a defect.
#
# The old pair also disagreed on what counts as large (`contains(runner,
# "large")` versus a list including `8-core`) and both read only the string
# form of `runs-on`, so `runs-on: [self-hosted, gpu]` was invisible to each.

# Substring-matched, because the size is a suffix on an otherwise arbitrary
# label: `ubuntu-latest-16-cores`, `ubuntu-22.04-xlarge`, `gpu-a100`. Kept to
# fragments that only appear in a size or accelerator label — `large` matches
# `xlarge` and `2xlarge` on its own, so those need no entry.
_size_markers := [
	"large",
	"gpu",
	"cuda",
	"8-core",
	"16-core",
	"32-core",
	"64-core",
	"96-core",
	"metal",
]

_is_large_runner(job) if {
	some label in wf.runs_on_labels(job)
	some marker in _size_markers
	contains(label, marker)
}

# Work that plausibly needs the capacity. Deliberately generous: the cost of a
# false positive here is telling someone their build machine is too big.
_heavy_run_keywords := [
	"build",
	"compile",
	"train",
	"cmake",
	"make ",
	"ninja",
	"bazel",
	"cargo ",
	"gradle",
	"mvn ",
	"webpack",
	"tsc ",
	"pytest",
	"go test",
	"npm test",
	"docker build",
	"buildx",
	"ffmpeg",
	"benchmark",
]

_heavy_actions := {
	"docker/build-push-action",
	"docker/bake-action",
	"gradle/actions/setup-gradle",
	"gradle/gradle-build-action",
	"goreleaser/goreleaser-action",
	"pypa/cibuildwheel",
	"nvidia/cuda",
}

_has_heavy_workload(job) if {
	some step in job.steps
	run := step.run
	is_string(run)
	some keyword in _heavy_run_keywords
	contains(lower(run), keyword)
}

_has_heavy_workload(job) if {
	some step in job.steps
	wf.action_name(step.uses) in _heavy_actions
}

# A matrix job runs its legs in parallel on separate runners; the size is a
# per-leg decision the step list does not describe, so it is left alone.
_has_heavy_workload(job) if job.strategy.matrix

violations contains violation if {
	some job_name, job in input.jobs
	_is_large_runner(job)
	not _has_heavy_workload(job)

	labels := concat(", ", sort(wf.runs_on_labels(job)))
	violation := {
		"rule": "runner_sizing",
		"severity": "medium",
		"category": "energy",
		"job": job_name,
		"line_start": object.get(job, "__start_line__", null),
		"line_end": object.get(job, "__end_line__", null),
		"message": sprintf("Job '%v' asks for a large runner (%v) but has no compute-intensive step. Move it to the default runner, or keep the large one on the job that needs it.", [job_name, labels]),
		"context": labels,
		"discriminator": job_name,
	}
}
