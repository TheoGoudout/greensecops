package greensecops.ci_workflow.security.oidc_not_used_test

import data.greensecops.ci_workflow.security.oidc_not_used
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
	violations := oidc_not_used.violations with input as {
		"jobs": {
			"deploy": {
				"env": {"GCP_SA_KEY": "${{ secrets.GCP_KEY }}"},
				"steps": [],
			},
		},
	}
	count(violations) == 1
	some v in violations
	v.job == "deploy"
}

test_no_violation_no_static_creds if {
	violations := oidc_not_used.violations with input as {"jobs": {"deploy": {"steps": [{"uses": "google-github-actions/auth@v2"}]}}}
	count(violations) == 0
}

# The shape this rule exists to replace, and the one it could not see: the
# credential handed to the cloud login action as an input rather than an env
# var.
test_violation_for_aws_credentials_passed_as_inputs if {
	violations := oidc_not_used.violations with input as {"jobs": {"deploy": {"steps": [{
		"uses": "aws-actions/configure-aws-credentials@v4",
		"with": {
			"aws-access-key-id": "${{ secrets.AWS_ACCESS_KEY_ID }}",
			"aws-secret-access-key": "${{ secrets.AWS_SECRET_ACCESS_KEY }}",
			"aws-region": "eu-west-1",
		},
	}]}}}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

test_no_violation_when_the_action_assumes_a_role if {
	violations := oidc_not_used.violations with input as {"jobs": {"deploy": {"steps": [{
		"uses": "aws-actions/configure-aws-credentials@v4",
		"with": {"role-to-assume": "arn:aws:iam::1:role/ci", "aws-region": "eu-west-1"},
	}]}}}
	count(violations) == 0
}

test_violation_for_a_gcp_service_account_key_input if {
	violations := oidc_not_used.violations with input as {"jobs": {"deploy": {"steps": [{
		"uses": "google-github-actions/auth@v2",
		"with": {"credentials_json": "${{ secrets.GCP_SA_KEY }}"},
	}]}}}
	count(violations) == 1
}
