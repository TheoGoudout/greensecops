package greensecops.ci_workflow.maintainability.adhoc_package_install_test

import data.greensecops.ci_workflow.maintainability.adhoc_package_install as rule
import rego.v1

test_violation_npm_global_install if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "npm install -g typescript"},
	]}}}
	count(violations) == 1
	some v in violations
	v.rule == "adhoc_package_install"
	v.context == "npm"
}

test_violation_npm_short_global if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "npm i -g yarn"},
	]}}}
	count(violations) == 1
}

test_violation_go_install_latest if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "go install github.com/mikefarah/yq/v4@latest"},
	]}}}
	count(violations) == 1
	some v in violations
	v.context == "go"
}

test_violation_cargo_install_without_locked if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "cargo install cargo-audit"},
	]}}}
	count(violations) == 1
}

test_violation_gem_install_without_version if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "gem install bundler"},
	]}}}
	count(violations) == 1
}

test_violation_pip_install_bare_package if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "pip install requests"},
	]}}}
	count(violations) == 1
	some v in violations
	v.context == "pip"
}

# ─── Does not fire ───────────────────────────────────────────────────────────

# The lockfile-driven form, which is what examples/deploy.yml runs.
test_no_violation_npm_ci if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "npm ci && npm run build"},
	]}}}
	count(violations) == 0
}

# A local `npm install` resolves against package.json; only -g is ad hoc.
test_no_violation_npm_local_install if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "npm install && npm run build"},
	]}}}
	count(violations) == 0
}

test_no_violation_go_install_pinned if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "go install github.com/mikefarah/yq/v4@v4.44.3"},
	]}}}
	count(violations) == 0
}

test_no_violation_cargo_install_locked if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "cargo install --locked cargo-audit"},
	]}}}
	count(violations) == 0
}

test_no_violation_gem_install_versioned if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "gem install -v 2.5.0 bundler"},
	]}}}
	count(violations) == 0
}

test_no_violation_pip_requirements_file if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "pip install -r requirements.txt"},
	]}}}
	count(violations) == 0
}

# This repository's own opa.yml runs exactly this. A rule that reported it would
# be wrong about the corpus it ships with.
test_no_violation_pip_with_version_specifiers if {
	violations := rule.violations with input as {"jobs": {"opa": {"steps": [
		{"run": "pip install \"ruamel.yaml>=0.18,<0.19\" \"python-hcl2>=6.1,<7.0\""},
	]}}}
	count(violations) == 0
}

# deploy-reusable.yml pins through a shell variable.
test_no_violation_pip_version_from_shell_variable if {
	violations := rule.violations with input as {"jobs": {"deploy": {"steps": [
		{"run": "pip install \"ansible-core${ANSIBLE_CORE_VERSION}\""},
	]}}}
	count(violations) == 0
}

test_no_violation_pip_editable_local if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "pip install -e ."},
	]}}}
	count(violations) == 0
}

test_no_violation_pip_local_path if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "pip install ."},
	]}}}
	count(violations) == 0
}

# A command shown in a comment is not a command that runs.
test_no_violation_install_in_comment if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"run": "# npm install -g typescript\nnpm ci"},
	]}}}
	count(violations) == 0
}

test_no_violation_no_run_step if {
	violations := rule.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
	]}}}
	count(violations) == 0
}
