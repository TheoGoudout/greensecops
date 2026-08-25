package greensecops.iac_ansible.reliability.ignore_errors_true_test

import data.greensecops.iac_ansible.reliability.ignore_errors_true as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(extra) := object.union(
	{
		"name": "Remove the old unit file",
		"__module__": "ansible.builtin.command",
		"__args__": {"_raw_params": "rm /etc/systemd/system/old.service"},
		"__start_line__": 5,
		"__end_line__": 7,
		"__task_index__": 0,
	},
	extra,
)

test_violation_when_true if {
	violations := rule.violations with input as _file([_task({"ignore_errors": true})])
	count(violations) == 1
	some v in violations
	v.line_start == 5
}

test_violation_for_string_yes if {
	violations := rule.violations with input as _file([_task({"ignore_errors": "yes"})])
	count(violations) == 1
}

test_no_violation_when_false if {
	violations := rule.violations with input as _file([_task({"ignore_errors": false})])
	count(violations) == 0
}

test_no_violation_when_absent if {
	violations := rule.violations with input as _file([_task({})])
	count(violations) == 0
}

test_no_violation_for_failed_when if {
	violations := rule.violations with input as _file([_task({"failed_when": "rc not in [0, 2]"})])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"steps": []}
	count(violations) == 0
}
