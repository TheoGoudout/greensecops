package greensecops.iac_ansible.maintainability.task_missing_name_test

import data.greensecops.iac_ansible.maintainability.task_missing_name as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(extra) := object.union(
	{
		"__module__": "ansible.builtin.file",
		"__args__": {"path": "/opt/app", "state": "directory"},
		"__start_line__": 2,
		"__end_line__": 5,
		"__task_index__": 0,
	},
	extra,
)

test_violation_when_unnamed if {
	violations := rule.violations with input as _file([_task({})])
	count(violations) == 1
	some v in violations
	v.context == "ansible.builtin.file"
}

test_no_violation_when_named if {
	violations := rule.violations with input as _file([_task({"name": "Create the application directory"})])
	count(violations) == 0
}

test_no_violation_for_an_empty_file if {
	violations := rule.violations with input as _file([])
	count(violations) == 0
}

# Unnamed tasks have no name to key a fingerprint on, so the ordinal is what
# keeps two of them distinct.
test_each_unnamed_task_is_its_own_finding if {
	second := _task({"__task_index__": 1, "__module__": "ansible.builtin.copy"})
	violations := rule.violations with input as _file([_task({}), second])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"steps": [{"run": "make"}]}
	count(violations) == 0
}
