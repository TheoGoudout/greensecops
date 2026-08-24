# METADATA
# title: Untrusted value written to the environment file
# description: "A run step appends a shell-expanded value to $GITHUB_ENV or $GITHUB_PATH. The environment file is parsed line by line, so a value containing a newline defines additional variables of the attacker's choosing — LD_PRELOAD, NODE_OPTIONS or PATH among them — which then apply to every later step in the job. Routing a value through env: makes it safe to use in a script, but not safe to write here; this is the step that turns a contained value back into arbitrary control over the job."
# custom:
#   severity: high
#   severity_weight: 2.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         label:
#           runs-on: ubuntu-latest
#           env:
#             PR_TITLE: ${{ github.event.pull_request.title }}
#           steps:
#             - run: echo "TITLE=$PR_TITLE" >> "$GITHUB_ENV"
#     good: |
#       jobs:
#         label:
#           runs-on: ubuntu-latest
#           env:
#             PR_TITLE: ${{ github.event.pull_request.title }}
#           steps:
#             - run: echo "The title is $PR_TITLE"
#     fix: |
#       Use the value directly from env: in the step that needs it rather than promoting it to the job environment. Where a later step genuinely needs it, write it to $GITHUB_OUTPUT with a random delimiter heredoc, which is length-delimited rather than newline-delimited, and read it as a step output.
package greensecops.ci_workflow.security.github_env_injection

import rego.v1

# A write to the environment file whose value comes from a variable rather than
# a literal. `>> $GITHUB_ENV` with a constant on the left is fine; it is the
# expansion that can carry a newline.
#
# Scoped deliberately to shell-variable expansion. A `${{ }}` expression
# interpolated straight into the same line is already reported by
# `script_injection_expression`, and two findings on one line is noise. What is
# left here is the case that rule cannot see: a value correctly routed through
# `env:` — safe to *use* — being written somewhere it becomes unsafe again.
_env_file_write_pattern := `\$\{?(GITHUB_ENV|GITHUB_PATH)\}?`

# Variables the runner sets, not the event. `$GITHUB_SHA` is a commit id,
# `$RUNNER_OS` is a platform name, and neither can contain a newline — so
# `echo "SHA=$GITHUB_SHA" >> "$GITHUB_ENV"` is not an injection. Matching any
# `$VAR` reported every one of those at high severity, which is most of the
# legitimate writes to the environment file in existence.
_trusted_prefixes := ["GITHUB_", "RUNNER_"]

_trusted_names := {"HOME", "PWD", "CI", "USER", "SHELL", "PATH", "TMPDIR", "HOSTNAME", "OSTYPE"}

_is_trusted(name) if {
	some prefix in _trusted_prefixes
	startswith(name, prefix)
}

_is_trusted(name) if name in _trusted_names

_expanded_names(line) := {name |
	some match in regex.find_all_string_submatch_n(`\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?`, _before_redirect(line), -1)
	name := match[1]
}

_expands_a_variable(line) if {
	some name in _expanded_names(line)
	not _is_trusted(name)
}

_before_redirect(line) := split(line, ">>")[0]

_writes_expanded_value(run) if {
	some line in split(run, "\n")
	regex.match(_env_file_write_pattern, line)
	contains(line, ">>")
	_expands_a_variable(line)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	run := step.run
	is_string(run)
	_writes_expanded_value(run)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "github_env_injection",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' appends an expanded value to the environment file. The file is parsed line by line, so a newline in that value defines further variables — PATH or NODE_OPTIONS among them — for every later step in the job.", [step_label, job_name]),
		"context": "GITHUB_ENV",
	}
}
