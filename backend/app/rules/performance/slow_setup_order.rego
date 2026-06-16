package greensecops.performance.slow_setup_order

import rego.v1

# Detects jobs where a dependency-install step appears before a lint/typecheck
# step. Moving fast-fail checks (lint, typecheck) before installs gives faster
# feedback and wastes less compute on bad code.

_is_setup_step(step) if {
	startswith(step.uses, "actions/setup-")
}

_is_install_run(step) if {
	run := step.run
	some keyword in ["install", "pip install", "npm install", "yarn install", "poetry install"]
	contains(run, keyword)
}

_is_lint_step(step) if {
	run := step.run
	some keyword in ["lint", "typecheck", "mypy", "eslint", "ruff"]
	contains(run, keyword)
}

violations contains violation if {
	some job_name, job in input.jobs
	steps := job.steps

	some setup_idx in numbers.range(0, count(steps) - 1)
	_is_setup_step(steps[setup_idx])

	some install_idx in numbers.range(setup_idx + 1, count(steps) - 1)
	_is_install_run(steps[install_idx])

	some lint_idx in numbers.range(install_idx + 1, count(steps) - 1)
	_is_lint_step(steps[lint_idx])

	violation := {
		"rule": "slow_setup_order",
		"severity": "low",
		"category": "performance",
		"job": job_name,
		"message": sprintf("Job '%v' installs dependencies before running lint/typecheck. Move fast-fail checks earlier to reduce wasted compute.", [job_name]),
		"context": null,
	}
}
