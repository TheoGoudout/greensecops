package greensecops.iac_ansible.reliability.get_url_without_checksum_test

import data.greensecops.iac_ansible.reliability.get_url_without_checksum as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "roles/docker/tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

_task(args) := {
	"name": "Install the compose plugin",
	"__module__": "ansible.builtin.get_url",
	"__args__": args,
	"__start_line__": 8,
	"__end_line__": 16,
	"__task_index__": 1,
}

test_violation_without_checksum if {
	violations := rule.violations with input as _file([_task({"url": "https://x/y", "dest": "/usr/bin/y"})])
	count(violations) == 1
	some v in violations
	v.severity == "high"
	v.line_start == 8
}

test_no_violation_with_checksum if {
	violations := rule.violations with input as _file([_task({"url": "https://x/y", "checksum": "sha256:abc"})])
	count(violations) == 0
}

test_no_violation_with_templated_checksum if {
	violations := rule.violations with input as _file([_task({"checksum": "sha256:{{ sha }}"})])
	count(violations) == 0
}

test_no_violation_for_uri_module if {
	task := object.union(_task({}), {"__module__": "ansible.builtin.uri"})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"variable": {}}
	count(violations) == 0
}
