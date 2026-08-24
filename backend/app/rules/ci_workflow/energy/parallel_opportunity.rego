# METADATA
# title: Sequential jobs without dependency
# description: "Three or more jobs are chained with needs: while passing nothing between them — no job outputs, no uploaded artifacts. Each link makes the next job wait for a runner it did not need to wait for, so the pipeline takes as long as the sum of its parts instead of its longest part. A chain that does carry data is not this, and is not reported."
# custom:
#   severity: low
#   severity_weight: 0.6
#   detection: heuristic
#   examples:
#     bad: |
#       jobs:
#         lint:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run lint
#         test:
#           needs: lint
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm test
#         build:
#           needs: test
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     good: |
#       jobs:
#         lint:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run lint
#         test:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm test
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     fix: |
#       Drop the needs: links between jobs that do not consume each other's outputs or artifacts. GitHub runs independent jobs in parallel, so lint, test and build finish in the time of the slowest rather than the sum of all three. Keep needs: where a job genuinely reads a previous job's output or downloads its artifact.
package greensecops.ci_workflow.energy.parallel_opportunity

import data.greensecops.lib.workflow as wf
import rego.v1

_uploads_artifact(job) if {
	some step in job.steps
	contains(step.uses, "actions/upload-artifact")
}

_downloads_artifact(job) if {
	some step in job.steps
	contains(step.uses, "actions/download-artifact")
}

# A link carries data if the downstream job reads the upstream job's outputs, or
# if the upstream uploads an artifact the downstream downloads. Either way the
# ordering is load-bearing and dropping it would break the pipeline.
_link_carries_data(upstream_name, _, downstream_job) if {
	wf.job_outputs_consumed(upstream_name)
	regex.match(
		sprintf(`needs\.%v\.outputs\.`, [regex.replace(upstream_name, `[.*+?^${}()|\[\]\\]`, `\\$0`)]),
		json.marshal(downstream_job),
	)
}

_link_carries_data(_, upstream_job, downstream_job) if {
	_uploads_artifact(upstream_job)
	_downloads_artifact(downstream_job)
}

# A -> B -> C where neither link carries anything. The previous version fired on
# any chain of depth two, which is the shape of every ordinary pipeline, and
# never checked whether the jobs shared outputs — the one thing its own message
# asked the reader to consider.
_idle_chains contains chain if {
	some c_name, c_job in input.jobs
	some b_name in wf.job_needs(c_job)
	b_job := input.jobs[b_name]
	some a_name in wf.job_needs(b_job)
	a_job := input.jobs[a_name]

	not _link_carries_data(b_name, b_job, c_job)
	not _link_carries_data(a_name, a_job, b_job)

	chain := sprintf("%v -> %v -> %v", [a_name, b_name, c_name])
}

# One finding for the workflow, not one per (a, b, c) triple. A diamond produced
# a combinatorial number of identical findings before, all of which collapsed to
# a single issue on the dedup key anyway — so the extra ones were pure noise with
# an arbitrary winner deciding the message.
violations contains violation if {
	chains := _idle_chains
	count(chains) > 0
	listed := concat("; ", sort(chains))

	violation := {
		"rule": "parallel_opportunity",
		"severity": "low",
		"category": "energy",
		"job": null,
		"message": sprintf("Jobs are chained with needs: but pass no outputs or artifacts between them (%v). Check whether the ordering is required — a deploy that must precede a cache purge is a real dependency the file cannot express any other way. Where it is not, dropping the link lets the jobs start together.", [listed]),
		"context": listed,
		"discriminator": "needs-chain",
	}
}
