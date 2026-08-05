# METADATA
# title: Job grants itself more token scopes than the workflow default
# description: A job declares a permissions block granting write on a scope the workflow-level default does not. A job-level block replaces the default outright rather than intersecting with it, so this is how a workflow that looks least-privilege at the top ends up running a job with more authority than the file appears to grant. The workflow default is what a reviewer reads and remembers; the job block is forty lines further down. Widening in a job is legitimate — a release job genuinely needs contents write — but it should be visible, which is what this rule makes it.
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

_workflow_grants_write(scope) if input.permissions == "write-all"

_workflow_grants_write(scope) if {
	is_object(input.permissions)
	input.permissions[scope] == "write"
}

violations contains violation if {
	some job_name, job in input.jobs

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
