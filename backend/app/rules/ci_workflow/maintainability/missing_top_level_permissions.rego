# METADATA
# title: No top-level permissions block
# description: The workflow declares no permissions at all, so every job gets whatever the repository's default happens to be. That default is a repository setting rather than anything visible here, it differs between repositories, and an administrator can change it for all of them at once — so the token's scope is decided somewhere the workflow does not say. Declaring it makes the grant explicit and reviewable, and is what the excessive_token_permissions rule can then be read against.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         push:
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: make build
#     good: |
#       on:
#         push:
#       permissions:
#         contents: read
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: make build
#     fix: |
#       Add a top-level permissions block granting only what the workflow needs — contents: read covers a build that only checks out code. Widen it on the individual job that needs more, rather than at the top where it applies to every job.
package greensecops.ci_workflow.maintainability.missing_top_level_permissions

import rego.v1

# A job-level block covers that job, so a workflow where *every* job declares
# one has made the decision explicitly and does not need the top-level one.
_every_job_declares_permissions if {
	count(input.jobs) > 0
	every _, job in input.jobs {
		job.permissions
	}
}

violations contains violation if {
	not input.permissions
	not _every_job_declares_permissions

	violation := {
		"rule": "missing_top_level_permissions",
		"severity": "low",
		"category": "maintainability",
		"message": "The workflow declares no permissions, so its token scope comes from a repository setting this file does not state. Add a top-level permissions block — contents: read is the usual starting point.",
		"context": "permissions",
		"discriminator": "workflow",
	}
}
