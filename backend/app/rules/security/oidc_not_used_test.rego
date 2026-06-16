package greensecops.security.oidc_not_used_test

import data.greensecops.security.oidc_not_used
import rego.v1

test_violation_aws_static_creds_in_workflow_env if {
	violations := oidc_not_used.violations with input as {
		"env": {
			"AWS_ACCESS_KEY_ID": "${{ secrets.AWS_ACCESS_KEY_ID }}",
			"AWS_SECRET_ACCESS_KEY": "${{ secrets.AWS_SECRET_ACCESS_KEY }}",
		},
		"jobs": {},
	}
	count(violations) == 2
	some v in violations
	v.rule == "oidc_not_used"
}

test_violation_gcp_sa_key_in_job_env if {
	violations := oidc_not_used.violations with input as {"jobs": {"deploy": {
		"env": {"GCP_SA_KEY": "${{ secrets.GCP_KEY }}"},
		"steps": [],
	}}}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}

test_no_violation_no_static_creds if {
	violations := oidc_not_used.violations with input as {"jobs": {"deploy": {"steps": [{"uses": "google-github-actions/auth@v2"}]}}}
	count(violations) == 0
}
