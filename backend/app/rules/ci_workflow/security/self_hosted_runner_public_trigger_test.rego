package greensecops.ci_workflow.security.self_hosted_runner_public_trigger_test

import data.greensecops.ci_workflow.security.self_hosted_runner_public_trigger as self_hosted_pr
import rego.v1

# `runs-on` has three spellings — a bare label, a list of labels, and an object
# with `group`/`labels` — and a self-hosted runner is usually selected by
# combining `self-hosted` with more labels.

_wf(on, runs_on) := {
	"on": on,
	"jobs": {"build": {"runs-on": runs_on, "steps": [{"uses": "actions/checkout@v5"}]}},
}

test_violation_for_a_bare_self_hosted_label if {
	violations := self_hosted_pr.violations with input as _wf({"pull_request": null}, "self-hosted")
	count(violations) == 1
	some v in violations
	v.job == "build"
}

test_violation_for_a_label_list if {
	violations := self_hosted_pr.violations with input as _wf({"pull_request": null}, ["self-hosted", "linux", "x64"])
	count(violations) == 1
}

test_violation_for_the_object_form if {
	violations := self_hosted_pr.violations with input as _wf(
		{"pull_request": null},
		{"group": "builders", "labels": ["self-hosted", "linux"]},
	)
	count(violations) == 1
}

test_violation_for_the_list_trigger_form if {
	violations := self_hosted_pr.violations with input as _wf(["push", "pull_request"], "self-hosted")
	count(violations) == 1
}

test_violation_for_pull_request_target if {
	violations := self_hosted_pr.violations with input as _wf({"pull_request_target": null}, "self-hosted")
	count(violations) == 1
}

test_no_violation_on_a_github_hosted_runner if {
	violations := self_hosted_pr.violations with input as _wf({"pull_request": null}, "ubuntu-latest")
	count(violations) == 0
}

# A self-hosted runner on a push-only workflow runs code that is already on the
# branch, which is not this finding.
test_no_violation_without_a_pull_request_trigger if {
	violations := self_hosted_pr.violations with input as _wf({"push": {"branches": ["main"]}}, "self-hosted")
	count(violations) == 0
}

test_no_violation_for_a_large_github_runner if {
	violations := self_hosted_pr.violations with input as _wf({"pull_request": null}, "ubuntu-latest-16-cores")
	count(violations) == 0
}

test_each_self_hosted_job_is_its_own_finding if {
	violations := self_hosted_pr.violations with input as {
		"on": {"pull_request": null},
		"jobs": {
			"build": {"runs-on": "self-hosted", "steps": []},
			"test": {"runs-on": ["self-hosted", "gpu"], "steps": []},
			"lint": {"runs-on": "ubuntu-latest", "steps": []},
		},
	}
	count(violations) == 2
	{v.discriminator | some v in violations} == {"build", "test"}
}
