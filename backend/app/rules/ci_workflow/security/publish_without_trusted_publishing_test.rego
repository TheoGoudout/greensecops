package greensecops.ci_workflow.security.publish_without_trusted_publishing_test

import data.greensecops.ci_workflow.security.publish_without_trusted_publishing as rule
import rego.v1

test_violation_pypi_action_with_password if {
	violations := rule.violations with input as {"jobs": {"publish": {"steps": [{
		"uses": "pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc",
		"with": {"password": "${{ secrets.PYPI_API_TOKEN }}"},
	}]}}}
	count(violations) == 1
	some v in violations
	v.rule == "publish_without_trusted_publishing"
	v.step_index == 0
}

test_violation_npm_publish_with_step_token if {
	violations := rule.violations with input as {"jobs": {"publish": {"steps": [{
		"name": "Publish",
		"run": "npm publish --access public",
		"env": {"NODE_AUTH_TOKEN": "${{ secrets.NPM_TOKEN }}"},
	}]}}}
	count(violations) == 1
}

# A token bound at the top of the file is readable by the publish command just
# the same, and is if anything worse.
test_violation_npm_publish_with_workflow_env_token if {
	violations := rule.violations with input as {
		"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
		"jobs": {"publish": {"steps": [{"run": "npm publish"}]}},
	}
	count(violations) == 1
}

test_violation_twine_upload if {
	violations := rule.violations with input as {"jobs": {"publish": {
		"env": {"TWINE_PASSWORD": "${{ secrets.PYPI_API_TOKEN }}"},
		"steps": [{"run": "twine upload dist/*"}],
	}}}
	count(violations) == 1
	some v in violations
	v.context == "TWINE_PASSWORD"
}

test_violation_gem_push if {
	violations := rule.violations with input as {"jobs": {"publish": {"steps": [{
		"run": "gem push pkg/*.gem",
		"env": {"GEM_HOST_API_KEY": "${{ secrets.RUBYGEMS_API_KEY }}"},
	}]}}}
	count(violations) == 1
}

test_violation_cargo_publish if {
	violations := rule.violations with input as {"jobs": {"publish": {"steps": [{
		"run": "cargo publish",
		"env": {"CARGO_REGISTRY_TOKEN": "${{ secrets.CRATES_TOKEN }}"},
	}]}}}
	count(violations) == 1
}

# A publish inside a longer script still counts.
test_violation_publish_mid_script if {
	violations := rule.violations with input as {"jobs": {"publish": {"steps": [{
		"run": "npm ci && npm run build && npm publish",
		"env": {"NODE_AUTH_TOKEN": "${{ secrets.NPM_TOKEN }}"},
	}]}}}
	count(violations) == 1
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# No password input is how Trusted Publishing is selected — this is the fix.
test_no_violation_pypi_action_without_password if {
	violations := rule.violations with input as {"jobs": {"publish": {
		"permissions": {"id-token": "write"},
		"steps": [{"uses": "pypa/gh-action-pypi-publish@76f52bc884231f62b9a034ebfe128415bbaabdfc"}],
	}}}
	count(violations) == 0
}

# Publishing with no stored token is the OIDC path.
test_no_violation_npm_publish_without_token if {
	violations := rule.violations with input as {"jobs": {"publish": {
		"permissions": {"id-token": "write"},
		"steps": [{"run": "npm publish"}],
	}}}
	count(violations) == 0
}

# A token in the environment that no publish command uses is somebody else's
# finding, not this one.
test_no_violation_token_without_publish if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"NPM_TOKEN": "${{ secrets.NPM_TOKEN }}"},
		"steps": [{"run": "npm ci && npm test"}],
	}}}
	count(violations) == 0
}

# Installing from a registry is not publishing to one.
test_no_violation_npm_install if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"NODE_AUTH_TOKEN": "${{ secrets.NPM_TOKEN }}"},
		"steps": [{"run": "npm ci"}],
	}}}
	count(violations) == 0
}

# The word "publish" inside another token must not match the command.
test_no_violation_unrelated_publish_word if {
	violations := rule.violations with input as {"jobs": {"build": {
		"env": {"NPM_TOKEN": "x"},
		"steps": [{"run": "./scripts/republish-docs.sh"}],
	}}}
	count(violations) == 0
}

test_no_violation_deploy_shaped_workflow if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "npm ci && npm run build"},
		{"run": "./deploy.sh", "env": {"API_KEY": "${{ secrets.API_KEY }}"}},
	]}}}
	count(violations) == 0
}
