# METADATA
# title: Deprecated workflow commands re-enabled
# description: "A step sets ACTIONS_ALLOW_UNSECURE_COMMANDS, which turns ::set-env and ::add-path back on. GitHub removed those commands because they are parsed out of a step's stdout: any string a step prints — a dependency's version banner, a test name, a fetched file — becomes an environment write or a PATH prepend for every later step in the job. Restoring them hands that primitive to whatever the job happens to log."
# custom:
#   severity: high
#   severity_weight: 1.8
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           env:
#             ACTIONS_ALLOW_UNSECURE_COMMANDS: "true"
#           steps:
#             - run: ./legacy-build.sh
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: |
#                 echo "BUILD_ID=$(./compute-id.sh)" >> "$GITHUB_ENV"
#                 echo "$PWD/bin" >> "$GITHUB_PATH"
#     fix: |
#       Delete the ACTIONS_ALLOW_UNSECURE_COMMANDS entry, then rewrite whatever depended on it: `echo "::set-env name=K::V"` becomes `echo "K=V" >> "$GITHUB_ENV"`, and `echo "::add-path::DIR"` becomes `echo "DIR" >> "$GITHUB_PATH"`. Both files are append-only and are read between steps, so the behaviour is the same without the stdout parsing.
package greensecops.ci_workflow.security.insecure_commands_enabled

import rego.v1

_KEY := "ACTIONS_ALLOW_UNSECURE_COMMANDS"

# The runner converts the value with the same helper it uses for every boolean
# input, so `"false"`, `"0"` and an empty string leave the commands disabled and
# are not findings. Matching that set exactly is what keeps this from firing on
# a workflow that sets the variable in order to turn the feature *off*.
_enabled(value) if {
	lower(sprintf("%v", [value])) in {"true", "1", "y", "yes", "on"}
}

violations contains violation if {
	_enabled(input.env[_KEY])

	violation := {
		"rule": "insecure_commands_enabled",
		"severity": "high",
		"category": "security",
		"job": null,
		"message": sprintf("Workflow-level env sets %v, re-enabling the removed ::set-env and ::add-path commands for every step of every job. Any line a step prints then becomes an environment or PATH write. Remove the variable and append to $GITHUB_ENV / $GITHUB_PATH instead.", [_KEY]),
		"context": _KEY,
		"discriminator": "workflow-env",
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	_enabled(job.env[_KEY])

	violation := {
		"rule": "insecure_commands_enabled",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' sets %v, re-enabling the removed ::set-env and ::add-path commands for all of its steps. Any line a step prints then becomes an environment or PATH write. Remove the variable and append to $GITHUB_ENV / $GITHUB_PATH instead.", [job_name, _KEY]),
		"context": _KEY,
		"discriminator": sprintf("%v:job-env", [job_name]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	_enabled(step.env[_KEY])

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "insecure_commands_enabled",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' sets %v, re-enabling the removed ::set-env and ::add-path commands. Any line the step prints then becomes an environment or PATH write. Remove the variable and append to $GITHUB_ENV / $GITHUB_PATH instead.", [step_label, job_name, _KEY]),
		"context": _KEY,
		"discriminator": sprintf("%v:%v:step-env", [job_name, step_index]),
	}
}
