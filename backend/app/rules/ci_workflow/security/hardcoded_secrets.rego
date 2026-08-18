# METADATA
# title: Potential hardcoded secret
# description: "An environment variable holds what looks like a real credential rather than a reference to one. A secret written into the workflow is readable by anyone who can read the repository, is copied into every fork and every clone, and survives in git history after it is removed — so it has to be rotated, not just deleted. Detection needs both halves of the evidence — a name suggesting a secret, and a value that actually looks like one. A recognised credential format is reported whatever the variable is called."
# custom:
#   severity: critical
#   severity_weight: 4.0
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           env:
#             API_KEY: "sk-prod-abc123def456"
#           steps:
#             - run: ./deploy.sh
#     good: |
#       jobs:
#         deploy:
#           env:
#             API_KEY: ${{ secrets.API_KEY }}
#           steps:
#             - run: ./deploy.sh
#     fix: |
#       Store the value in GitHub repository or environment secrets and reference it with ${{ secrets.NAME }}. Rotate it as well — a secret that has been committed is compromised from the moment it was pushed, and removing the line does not remove it from history.
package greensecops.ci_workflow.security.hardcoded_secrets

import data.greensecops.lib.workflow as wf
import rego.v1

# The name half of the evidence. Case-insensitive with optional separators,
# lifted from container_docker/security/compose_hardcoded_secret.rego, which had
# the better version of this pattern all along.
_secret_name_pattern := `(?i)(api_?key|access_?key|secret|password|passwd|credential|private_?key|token|auth)`

# A name match alone is not evidence. This rule used to fire on any non-empty
# string under a matching name, which made `SERVICE_PASSWORD_POSTGRES:
# testpassword` — a throwaway fixture for a Postgres container that lives for
# the length of one job — indistinguishable from a production credential, and
# reported it at critical. The generated fix then replaced it with an undefined
# `${{ secrets.* }}`, which is an empty string at runtime, which breaks the job.
# So the value has to carry evidence too.
_value_looks_secret(value) if wf.looks_high_entropy(value)

_is_candidate(value) if {
	is_string(value)
	value != ""
	not wf.is_expression(value)
	not wf.is_placeholder(value)
}

# Two independent grounds to report. A recognised credential format needs no
# help from the variable name — an AWS access key ID under a variable called
# `FOO` is still an AWS access key ID.
_finding(key, value) := "format" if {
	_is_candidate(value)
	wf.known_credential(value)
}

_finding(key, value) := "entropy" if {
	_is_candidate(value)
	not wf.known_credential(value)
	regex.match(_secret_name_pattern, key)
	_value_looks_secret(value)
}

_message(key, context_label, "format") := sprintf(
	"Env var '%v' in %v holds a value matching a known credential format. Move it to ${{ secrets.NAME }} and rotate it — it is in git history from the commit that added it.",
	[key, context_label],
)

_message(key, context_label, "entropy") := sprintf(
	"Env var '%v' in %v is named like a secret and holds a high-entropy literal rather than a reference. Use ${{ secrets.NAME }} instead, and rotate the value.",
	[key, context_label],
)

_check_env(env, job_name, context_label) := {violation |
	some key, value in env
	ground := _finding(key, value)
	violation := {
		"rule": "hardcoded_secrets",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"message": _message(key, context_label, ground),
		"context": key,
		"discriminator": key,
	}
}

violations contains violation if {
	some v in _check_env(input.env, null, "workflow-level env")
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some v in _check_env(job.env, job_name, sprintf("job '%v'", [job_name]))
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some step in job.steps
	step_label := object.get(step, "name", "unnamed step")
	some v in _check_env(step.env, job_name, sprintf("step '%v' in job '%v'", [step_label, job_name]))
	violation := v
}
