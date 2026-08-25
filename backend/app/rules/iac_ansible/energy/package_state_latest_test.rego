package greensecops.iac_ansible.energy.package_state_latest_test

import data.greensecops.iac_ansible.energy.package_state_latest
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "roles/web/tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Install nginx",
	"__module__": "ansible.builtin.apt",
	"__args__": args,
	"__start_line__": 2,
	"__end_line__": 5,
	"__task_index__": 0,
}

test_violation_when_state_is_latest if {
	violations := package_state_latest.violations with input as _file([_task({"name": "nginx", "state": "latest"})])
	count(violations) == 1
	some v in violations
	v.line_start == 2
	v.file_path == "roles/web/tasks/main.yml"
}

test_no_violation_when_state_is_present if {
	violations := package_state_latest.violations with input as _file([_task({"name": "nginx", "state": "present"})])
	count(violations) == 0
}

test_no_violation_when_state_absent if {
	violations := package_state_latest.violations with input as _file([_task({"name": "nginx"})])
	count(violations) == 0
}

test_no_violation_for_a_non_package_module if {
	task := object.union(_task({"state": "latest"}), {"__module__": "ansible.builtin.file"})
	violations := package_state_latest.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := package_state_latest.violations with input as {"jobs": {"build": {"steps": []}}}
	count(violations) == 0
}

test_each_task_is_its_own_finding if {
	second := object.union(_task({"name": "curl", "state": "latest"}), {"name": "Install curl", "__task_index__": 1})
	violations := package_state_latest.violations with input as _file([_task({"name": "nginx", "state": "latest"}), second])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
