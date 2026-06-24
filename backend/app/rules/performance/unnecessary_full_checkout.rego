# METADATA
# title: Unnecessary full git history checkout
# description: "fetch-depth: 0 is used but no git history analysis (changelog generation, git log, blame, or ref-range diff) is present in the workflow."
# custom:
#   severity: low
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#               with:
#                 fetch-depth: 0
#             - run: npm ci && npm run build
#     good: |
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm ci && npm run build
#     fix: |
#       Remove fetch-depth: 0 unless the job needs full git history (changelog generation, git log, semantic-release, or diff-based tools like prek/pre-commit that use --from-ref). Shallow clones are significantly faster.
package greensecops.performance.unnecessary_full_checkout

import rego.v1

_uses_git_history(steps) if {
	some step in steps
	run := step.run
	some cmd in ["git log", "git describe", "git tag", "git blame", "git shortlog", "CHANGELOG", "gitversion", "semantic-release", "standard-version", "--from-ref", "prek"]
	contains(run, cmd)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	uses := step.uses
	startswith(uses, "actions/checkout")
	step["with"]["fetch-depth"] == 0
	not _uses_git_history(job.steps)
	violation := {
		"rule": "unnecessary_full_checkout",
		"severity": "low",
		"category": "performance",
		"job": job_name,
		"message": sprintf("Job '%v' uses fetch-depth: 0 but no git history commands found. Remove fetch-depth: 0 to speed up checkout.", [job_name]),
		"context": "fetch-depth: 0",
	}
}
