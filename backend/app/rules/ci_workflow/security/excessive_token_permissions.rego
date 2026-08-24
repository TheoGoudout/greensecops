# METADATA
# title: Workflow token granted write-all
# description: "The workflow sets permissions: write-all, so every job runs with a GITHUB_TOKEN that can write to every scope the repository has — contents, packages, deployments, actions, issues, pull requests, security events. Any step in any job, including every third-party action, runs with all of it. This is the widest grant the token can carry and there is no repository for which it is the minimum."
# custom:
#   severity: critical
#   severity_weight: 3.0
#   detection: static_analysis
#   examples:
#     bad: |
#       permissions: write-all
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     good: |
#       permissions: {}
#       jobs:
#         build:
#           permissions:
#             contents: read
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     fix: |
#       Set permissions: {} at the workflow level and grant scopes on the individual jobs that need them. A job block replaces the default rather than adding to it, so each job states its whole grant and a reader can see it in one place.
package greensecops.ci_workflow.security.excessive_token_permissions

import rego.v1

# This rule used to carry three clauses at three severities — write-all
# (critical), more than three write scopes (high), and a job with no
# permissions block (medium) — while its METADATA declared only the worst.
# Everything downstream of the catalog therefore recorded a medium finding as
# critical: the docs page, the Rule row, and the severity weight the score is
# computed from. `tests/core/test_rule_registry.py` had to carve this rule out
# of the check that METADATA and body agree.
#
# The three are now separate: this one keeps `write-all`,
# `token_permissions_too_broad` takes the over-grant, and the third clause is
# gone — a job with no permissions block in a workflow with no top-level block
# is exactly what `missing_top_level_permissions` already reports, and
# reporting it twice at two severities helped nobody.

violations contains violation if {
	input.permissions == "write-all"

	violation := {
		"rule": "excessive_token_permissions",
		"severity": "critical",
		"category": "security",
		"job": null,
		"message": "Workflow sets permissions: write-all, so every step of every job — including every third-party action — runs with a token that can write to every scope. Declare only the scopes each job needs.",
		"context": "permissions: write-all",
		"discriminator": "workflow",
	}
}

# A job block replaces the workflow default rather than narrowing it, so
# `write-all` on a job is the same grant with the same reach.
violations contains violation if {
	some job_name, job in input.jobs
	job.permissions == "write-all"

	violation := {
		"rule": "excessive_token_permissions",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"line_start": object.get(job, "__start_line__", null),
		"line_end": object.get(job, "__end_line__", null),
		"message": sprintf("Job '%v' sets permissions: write-all, which replaces the workflow default with a token that can write to every scope.", [job_name]),
		"context": "permissions: write-all",
		"discriminator": job_name,
	}
}
