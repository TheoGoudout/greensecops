package greensecops.ci_workflow.maintainability.deprecated_runner_image_test

import data.greensecops.ci_workflow.maintainability.deprecated_runner_image as retired_runner
import rego.v1

_job(runs_on) := {"jobs": {"build": {"runs-on": runs_on, "steps": [{"run": "make build"}]}}}

test_violation_for_ubuntu_20_04 if {
	violations := retired_runner.violations with input as _job("ubuntu-20.04")
	count(violations) == 1
	some v in violations
	v.job == "build"
	v.context == "ubuntu-20.04"
}

test_violation_for_ubuntu_18_04 if {
	violations := retired_runner.violations with input as _job("ubuntu-18.04")
	count(violations) == 1
}

test_violation_for_windows_2019 if {
	violations := retired_runner.violations with input as _job("windows-2019")
	count(violations) == 1
}

test_violation_for_macos_11 if {
	violations := retired_runner.violations with input as _job("macos-11")
	count(violations) == 1
}

test_violation_in_a_label_list if {
	violations := retired_runner.violations with input as _job(["self-hosted", "ubuntu-20.04"])
	count(violations) == 1
}

test_violation_in_the_object_form if {
	violations := retired_runner.violations with input as _job({"group": "builders", "labels": ["ubuntu-18.04"]})
	count(violations) == 1
}

test_no_violation_for_a_supported_image if {
	violations := retired_runner.violations with input as _job("ubuntu-24.04")
	count(violations) == 0
}

test_no_violation_for_ubuntu_latest if {
	violations := retired_runner.violations with input as _job("ubuntu-latest")
	count(violations) == 0
}

test_no_violation_for_windows_2022 if {
	violations := retired_runner.violations with input as _job("windows-2022")
	count(violations) == 0
}

# Matched on the exact label, so a self-hosted runner whose label merely
# contains a retired name is not flagged.
test_no_violation_for_a_self_hosted_label_containing_a_retired_name if {
	violations := retired_runner.violations with input as _job(["self-hosted", "our-ubuntu-20.04-image"])
	count(violations) == 0
}

test_each_retired_job_is_its_own_finding if {
	violations := retired_runner.violations with input as {"jobs": {
		"build": {"runs-on": "ubuntu-20.04", "steps": []},
		"test": {"runs-on": "windows-2019", "steps": []},
		"lint": {"runs-on": "ubuntu-24.04", "steps": []},
	}}
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
