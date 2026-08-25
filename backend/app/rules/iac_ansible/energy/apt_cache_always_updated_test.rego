package greensecops.iac_ansible.energy.apt_cache_always_updated_test

import data.greensecops.iac_ansible.energy.apt_cache_always_updated
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Install nginx",
	"__module__": "ansible.builtin.apt",
	"__args__": args,
	"__start_line__": 3,
	"__end_line__": 7,
	"__task_index__": 0,
}

test_violation_when_cache_valid_time_absent if {
	violations := apt_cache_always_updated.violations with input as _file([_task({"update_cache": true})])
	count(violations) == 1
}

test_violation_for_string_yes if {
	violations := apt_cache_always_updated.violations with input as _file([_task({"update_cache": "yes"})])
	count(violations) == 1
}

test_no_violation_when_cache_valid_time_present if {
	violations := apt_cache_always_updated.violations with input as _file([_task({"update_cache": true, "cache_valid_time": 3600})])
	count(violations) == 0
}

test_no_violation_when_update_cache_false if {
	violations := apt_cache_always_updated.violations with input as _file([_task({"update_cache": false})])
	count(violations) == 0
}

test_no_violation_for_dnf if {
	task := object.union(_task({"update_cache": true}), {"__module__": "ansible.builtin.dnf"})
	violations := apt_cache_always_updated.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := apt_cache_always_updated.violations with input as {"services": {"api": {}}}
	count(violations) == 0
}
