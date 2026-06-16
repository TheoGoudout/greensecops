package greensecops.security.oidc_not_used

import rego.v1

# Detects static cloud credentials stored as env vars instead of using
# OIDC-based short-lived tokens, which reduces the blast radius of leaks.

_static_cred_keys := {
	"AWS_ACCESS_KEY_ID",
	"AWS_SECRET_ACCESS_KEY",
	"AZURE_CREDENTIALS",
	"GCP_SA_KEY",
}

_check_env_for_static_creds(env, job_name) := {violation |
	some key in _static_cred_keys
	env[key]
	violation := {
		"rule": "oidc_not_used",
		"severity": "high",
		"category": "security",
		"job": job_name,
		"message": sprintf("Static cloud credential '%v' found in env. Use OIDC (id-token: write + cloud provider OIDC action) instead of long-lived credentials.", [key]),
		"context": key,
	}
}

violations contains violation if {
	some v in _check_env_for_static_creds(input.env, null)
	violation := v
}

violations contains violation if {
	some job_name, job in input.jobs
	some v in _check_env_for_static_creds(job.env, job_name)
	violation := v
}
