package greensecops.iac_ansible.security.no_log_missing_on_secret_task_test

import data.greensecops.iac_ansible.security.no_log_missing_on_secret_task as rule
import rego.v1

_file(tasks) := {"files": [{
	"__ansible_file": "tasks/main.yml",
	"kind": "tasks",
	"tasks": tasks,
}]}

# `args` is a parameter rather than something `extra` overrides: object.union
# merges recursively, so an `__args__` passed through `extra` would be merged
# into the default rather than replacing it.
_task(args, extra) := object.union(
	{
		"name": "Create the application user",
		"__module__": "community.postgresql.postgresql_user",
		"__args__": args,
		"__start_line__": 2,
		"__end_line__": 6,
		"__task_index__": 0,
	},
	extra,
)

_secret_args := {"name": "app", "password": "{{ db_password }}"}

test_violation_without_no_log if {
	violations := rule.violations with input as _file([_task(_secret_args, {})])
	count(violations) == 1
	some v in violations
	v.context == "password"
}

# The realistic shape: the credential is nested in a request body, not a
# top-level module argument.
test_violation_for_a_nested_secret if {
	task := _task({"url": "https://api/x", "body": {"host": "h", "api_token": "{{ deploy_token }}"}}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 1
	some v in violations
	v.context == "body.api_token"
}

# List entries walk as numeric path segments, which must not be read as names.
test_no_violation_for_an_argv_list if {
	task := _task({"argv": ["aws", "ssm", "get-parameter"]}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_no_violation_with_no_log if {
	violations := rule.violations with input as _file([_task(_secret_args, {"no_log": true})])
	count(violations) == 0
}

# The parser propagates a block's no_log onto the tasks inside it, so a rule
# reading it off the flattened task sees the inherited value.
test_no_violation_when_no_log_is_inherited_from_a_block if {
	violations := rule.violations with input as _file([_task(_secret_args, {"no_log": true, "__block_depth__": 1})])
	count(violations) == 0
}

test_no_violation_for_an_ordinary_task if {
	task := _task({"path": "/opt/app", "state": "directory"}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_no_violation_for_a_plural_argument_name if {
	task := _task({"required_secrets": ["A", "B"]}, {})
	violations := rule.violations with input as _file([task])
	count(violations) == 0
}

test_silent_on_a_foreign_document if {
	violations := rule.violations with input as {"with": {"password": "x"}}
	count(violations) == 0
}
