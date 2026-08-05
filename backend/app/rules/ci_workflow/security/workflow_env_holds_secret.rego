# METADATA
# title: Secret exposed to the whole workflow through env
# description: A secret is bound to an environment variable at workflow level, so it is present in the environment of every step in every job — including third-party actions that have nothing to do with it. An action does not need to be malicious to leak it; anything that dumps the environment on error, or ships diagnostics, carries it out. Scoping the binding to the one step that needs it costs nothing and removes the exposure entirely.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       env:
#         NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
#       jobs:
#         publish:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v5
#             - run: npm publish
#     good: |
#       jobs:
#         publish:
#           runs-on: ubuntu-latest
#           steps:
#             - uses: actions/checkout@v5
#             - run: npm publish
#               env:
#                 NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
#     fix: |
#       Move the binding onto the single step that uses the secret. Workflow-level and job-level env reach every action that runs afterwards, which is a much wider blast radius than the one step actually needs.
package greensecops.ci_workflow.security.workflow_env_holds_secret

import rego.v1

_references_secret(value) if {
	is_string(value)
	regex.match(`\$\{\{\s*secrets\.[A-Za-z0-9_-]+\s*\}\}`, value)
}

violations contains violation if {
	some name, value in input.env
	_references_secret(value)

	violation := {
		"rule": "workflow_env_holds_secret",
		"severity": "medium",
		"category": "security",
		"message": sprintf("'%v' binds a secret at workflow level, so every step in every job runs with it in the environment — including third-party actions. Bind it on the step that needs it.", [name]),
		"context": name,
		"discriminator": sprintf("workflow:%v", [name]),
	}
}

# Job-level env has the same reach over every step in that job, which is still
# every third-party action it runs.
violations contains violation if {
	some job_name, job in input.jobs
	some name, value in job.env
	_references_secret(value)

	violation := {
		"rule": "workflow_env_holds_secret",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"message": sprintf("'%v' binds a secret for the whole of job '%v', so every step in it runs with the secret in the environment. Bind it on the step that needs it.", [name, job_name]),
		"context": name,
		"discriminator": sprintf("%v:%v", [job_name, name]),
	}
}
