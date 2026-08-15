package greensecops.ci_workflow.energy.caching_missing_test

import data.greensecops.ci_workflow.energy.caching_missing
import rego.v1

test_violation_setup_without_cache_emits_step_index if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
		{"uses": "actions/setup-node@v4"},
		{"run": "npm ci"},
	]}}}
	count(violations) == 1
	some v in violations
	v.step == "actions/setup-node@v4"
	v.step_index == 1
}

test_no_violation_cache_enabled if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/setup-node@v4", "with": {"cache": "npm"}},
		{"run": "npm ci"},
	]}}}
	count(violations) == 0
}

test_violation_no_setup_step_is_job_level if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/checkout@v4"},
		{"run": "pip install -r requirements.txt"},
	]}}}
	count(violations) == 1
	some v in violations
	not v.step_index
}

# ─── The false positives this rework exists to remove ─────────────────────────

# Running a task through a package manager is not installing dependencies. The
# old substring test matched `"uv "` and `"npm "`, so both of these counted.
test_no_violation_running_tasks_is_not_installing if {
	violations := caching_missing.violations with input as {"jobs": {
		"test": {"steps": [{"run": "uv run pytest"}]},
		"lint": {"steps": [{"run": "npm run lint"}]},
		"fmt": {"steps": [{"run": "cargo fmt --check"}]},
		"typecheck": {"steps": [{"run": "poetry run mypy ."}]},
	}}
	count(violations) == 0
}

test_no_violation_third_party_cache_action if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "Swatinem/rust-cache@v2"},
		{"run": "cargo build --release"},
	]}}}
	count(violations) == 0
}

# setup-uv caches by default from v6, so an install alongside it is cached.
test_no_violation_setup_uv_defaults_to_caching if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "astral-sh/setup-uv@v9"},
		{"run": "uv sync"},
	]}}}
	count(violations) == 0
}

test_violation_when_caching_explicitly_disabled if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "astral-sh/setup-uv@v9", "with": {"enable-cache": false}},
		{"run": "uv sync"},
	]}}}
	count(violations) == 1
}

test_no_violation_explicit_cache_action if {
	violations := caching_missing.violations with input as {"jobs": {"build": {"steps": [
		{"uses": "actions/cache@v4", "with": {"path": "~/.npm", "key": "npm-lock"}},
		{"run": "npm ci"},
	]}}}
	count(violations) == 0
}
