package greensecops.iac_ansible.energy.package_module_in_loop_test

import data.greensecops.iac_ansible.energy.package_module_in_loop
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(extra) := object.union(
	{
		"name": "Install base packages",
		"__module__": "ansible.builtin.dnf",
		"__args__": {"name": "{{ item }}", "state": "present"},
		"__start_line__": 2,
		"__end_line__": 9,
		"__task_index__": 0,
	},
	extra,
)

test_violation_for_loop if {
	violations := package_module_in_loop.violations with input as _file([_task({"loop": ["jq", "curl"]})])
	count(violations) == 1
}

test_violation_for_with_items if {
	violations := package_module_in_loop.violations with input as _file([_task({"with_items": ["jq"]})])
	count(violations) == 1
}

test_no_violation_without_a_loop if {
	violations := package_module_in_loop.violations with input as _file([_task({})])
	count(violations) == 0
}

test_no_violation_for_a_looped_file_task if {
	task := _task({"loop": ["/a", "/b"], "__module__": "ansible.builtin.file"})
	violations := package_module_in_loop.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := package_module_in_loop.violations with input as {"resource": []}
	count(violations) == 0
}
