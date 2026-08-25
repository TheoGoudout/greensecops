package greensecops.iac_ansible.energy.unarchive_remote_src_without_creates_test

import data.greensecops.iac_ansible.energy.unarchive_remote_src_without_creates as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Install the toolchain",
	"__module__": "ansible.builtin.unarchive",
	"__args__": args,
	"__start_line__": 2,
	"__end_line__": 7,
	"__task_index__": 0,
}

test_violation_when_creates_absent if {
	violations := rule.violations with input as _file([_task({"src": "https://x/t.tgz", "remote_src": true})])
	count(violations) == 1
}

test_no_violation_with_creates if {
	violations := rule.violations with input as _file([_task({"remote_src": true, "creates": "/opt/tc/bin/tc"})])
	count(violations) == 0
}

test_no_violation_for_a_local_archive if {
	violations := rule.violations with input as _file([_task({"src": "files/t.tgz"})])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"FROM": "alpine"}
	count(violations) == 0
}
