# METADATA
# title: Token granted write on more scopes than a job is likely to need
# description: "The workflow-level permissions block grants write on more than three scopes. Unlike write-all this is an explicit list, so it was written deliberately — but it is the default for every job in the file, and a job block replaces it rather than narrowing it, so the widest grant any single job needs becomes the grant every job that does not override it receives. Scopes belong on the jobs that use them."
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       permissions:
#         contents: write
#         packages: write
#         deployments: write
#         issues: write
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: make build
#     good: |
#       permissions: {}
#       jobs:
#         build:
#           permissions:
#             contents: read
#           runs-on: ubuntu-latest
#           steps:
#             - run: make build
#         release:
#           permissions:
#             contents: write
#             packages: write
#           runs-on: ubuntu-latest
#           steps:
#             - run: make publish
#     fix: |
#       Move each write scope onto the job that uses it and set the workflow default to permissions: {}. Where several jobs need the same wide grant, that is usually a sign the work belongs in one job rather than that the default should be raised.
package greensecops.ci_workflow.security.token_permissions_too_broad

import rego.v1

# Split out of `excessive_token_permissions`, which emitted this at `high` from
# a rule whose METADATA declared `critical`. Four is the threshold the original
# used and it is kept: three write scopes is a release job, and more than that
# is a default nobody re-reads.
_write_scopes := {scope |
	some scope, level in input.permissions
	level == "write"
}

violations contains violation if {
	is_object(input.permissions)
	scopes := _write_scopes
	count(scopes) > 3

	violation := {
		"rule": "token_permissions_too_broad",
		"severity": "high",
		"category": "security",
		"job": null,
		"message": sprintf("The workflow default grants write on %v scopes (%v), and every job that does not declare its own permissions block receives all of them. Grant each scope on the job that uses it.", [count(scopes), concat(", ", sort(scopes))]),
		"context": concat(", ", sort(scopes)),
		"discriminator": "workflow",
	}
}
