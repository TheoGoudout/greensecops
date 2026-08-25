package greensecops.iac_ansible.security.validate_certs_disabled_test

import data.greensecops.iac_ansible.security.validate_certs_disabled as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Fetch the release",
	"__module__": "ansible.builtin.get_url",
	"__args__": args,
	"__start_line__": 2,
	"__end_line__": 7,
	"__task_index__": 0,
}

test_violation_when_false if {
	violations := rule.violations with input as _file([_task({"url": "https://x/y", "validate_certs": false})])
	count(violations) == 1
}

test_violation_for_string_no if {
	violations := rule.violations with input as _file([_task({"validate_certs": "no"})])
	count(violations) == 1
}

test_no_violation_when_true if {
	violations := rule.violations with input as _file([_task({"validate_certs": true})])
	count(violations) == 0
}

test_no_violation_when_absent if {
	violations := rule.violations with input as _file([_task({"url": "https://x/y"})])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"jobs": {}}
	count(violations) == 0
}
