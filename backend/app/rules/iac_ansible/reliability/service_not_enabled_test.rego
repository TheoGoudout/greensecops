package greensecops.iac_ansible.reliability.service_not_enabled_test

import data.greensecops.iac_ansible.reliability.service_not_enabled as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "roles/docker/tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Start Docker",
	"__module__": "ansible.builtin.systemd_service",
	"__args__": args,
	"__start_line__": 40,
	"__end_line__": 45,
	"__task_index__": 3,
}

test_violation_when_enabled_absent if {
	violations := rule.violations with input as _file([_task({"name": "docker", "state": "started"})])
	count(violations) == 1
}

test_no_violation_when_enabled_true if {
	violations := rule.violations with input as _file([_task({"name": "docker", "state": "started", "enabled": true})])
	count(violations) == 0
}

test_no_violation_when_enabled_false_is_explicit if {
	violations := rule.violations with input as _file([_task({"state": "started", "enabled": false})])
	count(violations) == 0
}

test_no_violation_for_a_restart_handler if {
	violations := rule.violations with input as _file([_task({"name": "docker", "state": "restarted"})])
	count(violations) == 0
}

test_no_violation_when_state_absent if {
	violations := rule.violations with input as _file([_task({"name": "docker"})])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"services": {}}
	count(violations) == 0
}
