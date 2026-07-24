# METADATA
# title: Sequential jobs without dependency
# description: Jobs are chained together with a needs dependency into a sequential pipeline even though they may not consume each other's outputs. Running independent jobs in parallel reduces total pipeline duration and energy use.
# custom:
#   severity: low
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
#           steps:
#             - run: npm test
#         build:
#           needs: test
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
#       Remove unnecessary needs: dependencies between jobs that do not share outputs. GitHub Actions runs independent jobs in parallel by default, so a lint -> test -> build chain often serialises work that could run at once.
package greensecops.ci_workflow.energy.parallel_opportunity

import rego.v1

# Detects a sequential needs: chain spanning three or more jobs (job C needs
# job B, which in turn needs job A). A linear chain that deep usually forces
# work into sequence that could run in parallel — as opposed to a genuine
# fan-in (several jobs depending on one build), whose chain depth is only 1 and
# is left alone.

# The set of job names that a job declares in its needs: field, normalised
# across the scalar (needs: build) and list (needs: [build, lint]) forms.
_needs_names(job) := {job.needs} if is_string(job.needs)

_needs_names(job) := {n | some n in job.needs} if is_array(job.needs)

violations contains violation if {
	some c_name, c_job in input.jobs
	some b_name in _needs_names(c_job)
	some a_name in _needs_names(input.jobs[b_name])
	violation := {
		"rule": "parallel_opportunity",
		"severity": "low",
		"category": "energy",
		"job": null,
		"message": sprintf("Jobs form a sequential 'needs:' chain ('%v' -> '%v' -> '%v'). If these jobs do not consume each other's outputs, drop the needs: links so they run in parallel and cut total pipeline duration.", [a_name, b_name, c_name]),
		"context": null,
	}
}
