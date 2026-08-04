package greensecops.ci_workflow.maintainability.missing_top_level_permissions_test

import data.greensecops.ci_workflow.maintainability.missing_top_level_permissions as missing_permissions
import rego.v1

_steps := [{"run": "make build"}]

test_violation_when_nothing_declares_permissions if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": _steps}},
	}
	count(violations) == 1
	some v in violations
	v.discriminator == "workflow"
}

test_no_violation_with_a_top_level_block if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"permissions": {"contents": "read"},
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": _steps}},
	}
	count(violations) == 0
}

# `permissions: {}` grants nothing at all, which is the strictest possible
# declaration and emphatically a decision.
test_no_violation_for_an_empty_permissions_block if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"permissions": {},
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": _steps}},
	}
	count(violations) == 0
}

test_no_violation_for_the_read_all_shorthand if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"permissions": "read-all",
		"jobs": {"build": {"runs-on": "ubuntu-latest", "steps": _steps}},
	}
	count(violations) == 0
}

# Declaring it on every job is equally explicit, just spelled out per job.
test_no_violation_when_every_job_declares_its_own if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"jobs": {
			"build": {"permissions": {"contents": "read"}, "steps": _steps},
			"deploy": {"permissions": {"contents": "read", "id-token": "write"}, "steps": _steps},
		},
	}
	count(violations) == 0
}

# ...but one job left undeclared still falls back to the repository default.
test_violation_when_only_some_jobs_declare_permissions if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"jobs": {
			"build": {"permissions": {"contents": "read"}, "steps": _steps},
			"deploy": {"steps": _steps},
		},
	}
	count(violations) == 1
}

test_one_finding_per_workflow if {
	violations := missing_permissions.violations with input as {
		"on": {"push": null},
		"jobs": {
			"a": {"steps": _steps},
			"b": {"steps": _steps},
			"c": {"steps": _steps},
		},
	}
	count(violations) == 1
}
