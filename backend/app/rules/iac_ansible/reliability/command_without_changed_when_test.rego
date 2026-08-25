package greensecops.iac_ansible.reliability.command_without_changed_when_test

import data.greensecops.iac_ansible.reliability.command_without_changed_when as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(extra) := object.union(
	{
		"name": "Read the cluster status",
		"__module__": "ansible.builtin.command",
		"__args__": {"_raw_params": "/usr/bin/cluster status"},
		"__start_line__": 2,
		"__end_line__": 3,
		"__task_index__": 0,
	},
	extra,
)

test_violation_without_changed_when if {
	violations := rule.violations with input as _file([_task({})])
	count(violations) == 1
}

test_no_violation_with_changed_when_false if {
	violations := rule.violations with input as _file([_task({"changed_when": false})])
	count(violations) == 0
}

test_no_violation_with_changed_when_expression if {
	violations := rule.violations with input as _file([_task({"changed_when": "result.rc == 0"})])
	count(violations) == 0
}

test_no_violation_when_creates_guards_the_command if {
	task := _task({"__args__": {"_raw_params": "make", "creates": "/opt/out"}})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_violation_for_shell if {
	task := _task({"__module__": "ansible.builtin.shell"})
	violations := rule.violations with input as _file([task])
	count(violations) == 1
	some v in violations
	contains(v.message, "shell")
}

test_no_violation_for_a_state_module if {
	task := _task({"__module__": "ansible.builtin.file"})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"jobs": {}}
	count(violations) == 0
}
