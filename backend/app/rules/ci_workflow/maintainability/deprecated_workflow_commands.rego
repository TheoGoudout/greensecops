# METADATA
# title: Removed workflow command used
# description: A run step writes one of the workflow commands GitHub removed — set-output, save-state, set-env or add-path. They were disabled because a command written to stdout could be forged by anything a build printed, which made any tool that echoed untrusted text able to set an environment variable or prepend to PATH. They no longer do anything, so a step relying on one is silently passing nothing to whatever reads it.
# custom:
#   severity: low
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: echo "::set-output name=version::1.2.3"
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: echo "version=1.2.3" >> "$GITHUB_OUTPUT"
#     fix: |
#       Write to the environment files instead — $GITHUB_OUTPUT for set-output, $GITHUB_ENV for set-env, $GITHUB_PATH for add-path, $GITHUB_STATE for save-state. They take the value through a file rather than through stdout, which is what closes the forgery hole.
package greensecops.ci_workflow.maintainability.deprecated_workflow_commands

import rego.v1

_replacements := {
	"set-output": "$GITHUB_OUTPUT",
	"save-state": "$GITHUB_STATE",
	"set-env": "$GITHUB_ENV",
	"add-path": "$GITHUB_PATH",
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	script := step.run
	is_string(script)

	some command, replacement in _replacements
	regex.match(sprintf(`::%v[ :]`, [command]), script)

	violation := {
		"rule": "deprecated_workflow_commands",
		"severity": "low",
		"category": "maintainability",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Job '%v' uses the removed ::%v workflow command, which no longer does anything. Write to %v instead.", [job_name, command, replacement]),
		"context": command,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, command]),
	}
}
