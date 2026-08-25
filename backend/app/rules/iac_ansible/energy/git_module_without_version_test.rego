package greensecops.iac_ansible.energy.git_module_without_version_test

import data.greensecops.iac_ansible.energy.git_module_without_version
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Check out the application",
	"__module__": "ansible.builtin.git",
	"__args__": args,
	"__start_line__": 4,
	"__end_line__": 8,
	"__task_index__": 0,
}

test_violation_without_version if {
	violations := git_module_without_version.violations with input as _file([_task({"repo": "https://x/y.git", "dest": "/opt/app"})])
	count(violations) == 1
	some v in violations
	v.line_start == 4
}

test_no_violation_with_version if {
	violations := git_module_without_version.violations with input as _file([_task({"repo": "https://x/y.git", "version": "v1.0.0"})])
	count(violations) == 0
}

test_no_violation_for_another_module if {
	task := object.union(_task({}), {"__module__": "ansible.builtin.copy"})
	violations := git_module_without_version.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := git_module_without_version.violations with input as {"on": {"push": {}}}
	count(violations) == 0
}
