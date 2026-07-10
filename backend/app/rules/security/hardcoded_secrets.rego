# METADATA
# title: Potential hardcoded secret
# description: An environment variable name matches common secret patterns (API_KEY, TOKEN, PASSWORD, SECRET) and its value appears to be a literal string rather than a secret reference.
# custom:
#   severity: critical
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           env:
#             API_KEY: "sk-prod-abc123def456"
#             DB_PASSWORD: "MyP@ssw0rd!"
#           steps:
#             - run: ./deploy.sh
#     good: |
#       jobs:
#         deploy:
#           env:
#             API_KEY: ${{ secrets.API_KEY }}
#             DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
#           steps:
#             - run: ./deploy.sh
#     fix: |
#       Store secrets in GitHub repository or environment secrets and reference them with ${{ secrets.SECRET_NAME }}. Rotate any secrets that were previously hardcoded.
package greensecops.security.hardcoded_secrets

import rego.v1

# Detects env vars whose names suggest secrets (API_KEY, TOKEN, PASSWORD, etc.)
# but whose values are plain string literals instead of secret/var references.

_secret_name_pattern := `(API_KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL|PRIVATE_KEY)`

_is_secret_ref(value) if {
	startswith(value, "${{ secrets.")
}

_is_secret_ref(value) if {
	startswith(value, "${{ vars.")
}

_check_env(env, job_name, context_label) := {violation |
	some key, value in env
	is_string(value)
	value != ""
	regex.match(_secret_name_pattern, key)
	not _is_secret_ref(value)
	violation := {
		"rule": "hardcoded_secrets",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"message": sprintf("Env var '%v' in %v appears to contain a hardcoded secret. Use ${{ secrets.NAME }} instead.", [key, context_label]),
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
