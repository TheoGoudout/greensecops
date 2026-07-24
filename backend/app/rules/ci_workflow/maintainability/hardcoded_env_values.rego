# METADATA
# title: Hardcoded environment-specific values
# description: Values like URLs, bucket names, or region names are hardcoded in the workflow instead of being referenced from repository variables or secrets.
# custom:
#   severity: info
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         deploy:
#           env:
#             API_URL: https://api.production.example.com
#             BUCKET: my-app-artifacts
#           steps:
#             - run: ./deploy.sh
#     good: |
#       jobs:
#         deploy:
#           env:
#             API_URL: ${{ vars.API_URL }}
#             BUCKET: ${{ vars.ARTIFACT_BUCKET }}
#           steps:
#             - run: ./deploy.sh
#     fix: |
#       Move environment-specific values (URLs, bucket names, regions) to GitHub repository or environment variables and reference them with ${{ vars.VAR_NAME }}.
package greensecops.ci_workflow.maintainability.hardcoded_env_values

import rego.v1

# Detects env var values that look like URLs or cloud storage bucket names
# hardcoded as plain strings instead of secret/variable references.

_is_secret_ref(value) if {
	startswith(value, "${{")
}

_looks_like_url(value) if {
	startswith(value, "http://")
}

_looks_like_url(value) if {
	startswith(value, "https://")
}

_looks_like_bucket(value) if {
	some suffix in ["-bucket", "-artifacts", "-storage"]
	endswith(value, suffix)
}

_is_flagged_value(value) if {
	is_string(value)
	not _is_secret_ref(value)
	_looks_like_url(value)
}

_is_flagged_value(value) if {
	is_string(value)
	not _is_secret_ref(value)
	_looks_like_bucket(value)
}

_check_env(env, job_name) := {violation |
	some key, value in env
	_is_flagged_value(value)
	violation := {
		"rule": "hardcoded_env_values",
		"severity": "info",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Env var '%v' has a hardcoded value that looks like a URL or bucket name. Move environment-specific values to repository variables or secrets.", [key]),
		"context": key,
		"discriminator": key,
	}
}

violations contains violation if {
	some v in _check_env(input.env, null)
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some v in _check_env(job.env, job_name)
	violation := v
}
