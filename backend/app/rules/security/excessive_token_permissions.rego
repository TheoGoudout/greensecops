# METADATA
# title: Excessive GITHUB_TOKEN permissions
# description: "Workflow uses permissions: write-all (critical), grants write access to more than 3 scopes at the workflow level (high), or a job uses GitHub Actions without declaring any explicit permissions block (medium). The GITHUB_TOKEN should follow least privilege — declare only the permissions actually needed."
# custom:
#   severity: critical
#   detection: static_analysis
#   examples:
#     bad: |
#       permissions: write-all
#       jobs:
#         build:
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm run build
#     good: |
#       permissions: {}
#       jobs:
#         build:
#           permissions:
#             contents: read
#           steps:
#             - uses: actions/checkout@v4
#             - run: npm run build
#     fix: |
#       Replace write-all with a minimal permissions block declaring only the scopes the workflow actually needs. Set permissions: {} at the workflow level and add per-job overrides.
package greensecops.security.excessive_token_permissions

import rego.v1

violations contains violation if {
	perms := input.permissions
	perms == "write-all"
	violation := {
		"rule": "excessive_token_permissions",
		"severity": "critical",
		"category": "security",
		"job": null,
		"message": "Workflow uses permissions: write-all. Declare only the minimum required scopes.",
		"context": "permissions: write-all",
	}
}

violations contains violation if {
	perms := input.permissions
	is_object(perms)
	perms[_] == "write"
	count([p | perms[p] == "write"]) > 3
	violation := {
		"rule": "excessive_token_permissions",
		"severity": "high",
		"category": "security",
		"job": null,
		"message": "Workflow grants write permission to more than 3 scopes. Review and restrict to minimum required.",
		"context": null,
	}
}

violations contains violation if {
	not input.permissions
	some job_name, job in input.jobs
	not job.permissions
	some step in job.steps
	uses := step.uses
	startswith(uses, "actions/")
	violation := {
		"rule": "excessive_token_permissions",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' uses GitHub Actions without declaring explicit permissions. Add `permissions:` to restrict the GITHUB_TOKEN scope.", [job_name]),
		"context": null,
	}
}
