package greensecops.iac_ansible.security.world_writable_mode_test

import data.greensecops.iac_ansible.security.world_writable_mode as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Install the entrypoint",
	"__module__": "ansible.builtin.copy",
	"__args__": args,
	"__start_line__": 2,
	"__end_line__": 7,
	"__task_index__": 0,
}

test_violation_for_0777 if {
	violations := rule.violations with input as _file([_task({"mode": "0777"})])
	count(violations) == 1
	some v in violations
	v.context == "0777"
}

test_violation_for_three_digit_666 if {
	violations := rule.violations with input as _file([_task({"mode": "666"})])
	count(violations) == 1
}

test_violation_for_symbolic_o_plus_w if {
	violations := rule.violations with input as _file([_task({"mode": "o+w"})])
	count(violations) == 1
}

test_no_violation_for_0755 if {
	violations := rule.violations with input as _file([_task({"mode": "0755"})])
	count(violations) == 0
}

test_no_violation_for_0640 if {
	violations := rule.violations with input as _file([_task({"mode": "0640"})])
	count(violations) == 0
}

test_no_violation_for_a_templated_mode if {
	violations := rule.violations with input as _file([_task({"mode": "{{ file_mode }}"})])
	count(violations) == 0
}

test_no_violation_when_mode_absent if {
	violations := rule.violations with input as _file([_task({"src": "a", "dest": "/b"})])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"mode": "0777"}
	count(violations) == 0
}
