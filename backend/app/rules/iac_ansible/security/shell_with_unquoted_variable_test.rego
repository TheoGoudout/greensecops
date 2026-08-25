package greensecops.iac_ansible.security.shell_with_unquoted_variable_test

import data.greensecops.iac_ansible.security.shell_with_unquoted_variable as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "roles/docker/tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

# `args` is a parameter rather than something `extra` overrides: object.union
# merges recursively, so an `__args__` passed through `extra` would be merged
# into the default rather than replacing it — and an argv task would keep the
# `cmd` this rule keys on.
_task(args, extra) := object.union(
	{
		"name": "Log in to the registry",
		"__module__": "ansible.builtin.shell",
		"__args__": args,
		"__start_line__": 47,
		"__end_line__": 55,
		"__task_index__": 4,
	},
	extra,
)

_unquoted_cmd := {"cmd": "docker login {{ registry_host }}"}

test_violation_for_an_unquoted_expression if {
	violations := rule.violations with input as _file([_task(_unquoted_cmd, {})])
	count(violations) == 1
	some v in violations
	v.context == "{{ registry_host }}"
	v.line_start == 47
}

test_no_violation_when_quoted if {
	task := _task({"cmd": "docker login {{ registry_host | quote }}"}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_no_violation_when_quoted_without_spaces if {
	task := _task({"cmd": "docker login {{ registry_host|quote }}"}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_no_violation_for_a_plain_command if {
	task := _task({"cmd": "docker system prune --force"}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

# argv is handed to execve directly, so nothing re-parses it.
test_no_violation_for_argv if {
	task := _task({"argv": ["docker", "login", "{{ registry_host }}"]}, {"__module__": "ansible.builtin.command"})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_one_finding_per_task_however_many_expressions if {
	task := _task({"cmd": "aws ecr get-login-password --region {{ region }} | docker login {{ registry }}"}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 1
	some v in violations
	v.context == "{{ region }}, {{ registry }}"
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"run": "echo {{ x }}"}
	count(violations) == 0
}
