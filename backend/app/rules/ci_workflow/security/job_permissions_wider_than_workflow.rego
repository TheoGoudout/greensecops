# METADATA
# title: Job grants itself more token scopes than the workflow default
# description: "A job grants itself write on a scope the workflow-level default declares differently. A job block replaces the default outright rather than intersecting with it, so a workflow that reads as least-privilege at the top can run a job with more authority than the file appears to grant — and the default is what a reviewer remembers, forty lines above the job. A workflow whose default is the empty deny-all block is not this: from there a job block is the only thing granting anything, which is the tightest layout available and the one GitHub documents."
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       permissions:
#         contents: read
#       jobs:
#         build:
#           permissions:
#             contents: write
#             packages: write
#           runs-on: ubuntu-latest
#     good: |
#       permissions:
#         contents: read
#         packages: write
#       jobs:
#         build:
#           permissions:
#             contents: read
#           runs-on: ubuntu-latest
#         release:
#           permissions:
#             contents: read
#             packages: write
#           runs-on: ubuntu-latest
#     fix: |
#       Grant the extra scope only in the job that needs it and drop every scope that job does not use — a job block replaces the default rather than adding to it, so read scopes the job still needs must be restated. Where several jobs need the same widening, that is a sign the work belongs in one job rather than that the default should be raised.
package greensecops.ci_workflow.security.job_permissions_wider_than_workflow

import rego.v1

_workflow_grants_write(_) if input.permissions == "write-all"

_workflow_grants_write(scope) if {
	is_object(input.permissions)
	input.permissions[scope] == "write"
}

# `permissions: {}` is the deny-all baseline GitHub documents and this
# repository uses everywhere. From that starting point a job block is the only
# thing that grants anything, and granting one scope to one job is the tightest
# configuration available — every other job still has nothing. Reporting it
# inverted the advice: the rule fired thirteen times on the best-practice
# layout while a workflow with no `permissions:` at all, where the token keeps
# whatever the repository default is, went unreported. That case belongs to
# `missing_top_level_permissions`, which already owns it.
_workflow_denies_by_default if {
	is_object(input.permissions)
	count(input.permissions) == 0
}

violations contains violation if {
	some job_name, job in input.jobs

	not _workflow_denies_by_default

	perms := job.permissions
	is_object(perms)

	some scope, level in perms
	level == "write"
	not _workflow_grants_write(scope)

	violation := {
		"rule": "job_permissions_wider_than_workflow",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"line_start": object.get(job, "__start_line__", null),
		"line_end": object.get(job, "__end_line__", null),
		"message": sprintf("Job '%v' grants itself '%v: write', which the workflow default does not — a job block replaces the default rather than narrowing it.", [job_name, scope]),
		"context": sprintf("%v: write", [scope]),
		"discriminator": sprintf("%v:%v", [job_name, scope]),
	}
}
