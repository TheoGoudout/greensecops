# METADATA
# title: Secret-bearing task without no_log
# description: A task passes a credential-shaped argument without no_log, so Ansible prints the rendered value in its output and writes it to any log or CI transcript the run produces. Templating does not help — the log records the resolved value, not the expression.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Create the application user
#         community.postgresql.postgresql_user:
#           name: app
#           password: "{{ db_password }}"
#     good: |
#       - name: Create the application user
#         community.postgresql.postgresql_user:
#           name: app
#           password: "{{ db_password }}"
#         no_log: true
#     fix: |
#       Add no_log: true to the task. Where a block groups several such tasks, setting it on the block covers all of them.
package greensecops.iac_ansible.security.no_log_missing_on_secret_task

import data.greensecops.lib.ansible as ans
import rego.v1

# Credential-shaped argument names anywhere in the task's arguments, however
# deeply nested. `walk` rather than a top-level scan because the realistic case
# is nested: a uri body, a container's environment, a database module's
# connection block. The `is_string` guard drops the numeric path elements walk
# yields for list entries.
_secret_paths(task) := {joined |
	walk(object.get(task, "__args__", {}), [path, _])
	count(path) > 0
	name := path[count(path) - 1]
	is_string(name)
	ans.secret_name(name)
	joined := concat(".", [segment | some segment in path; is_string(segment)])
}

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	names := _secret_paths(task)
	count(names) > 0
	not ans.truthy(object.get(task, "no_log", false))
	listed := concat(", ", sort(names))
	violation := {
		"rule": "no_log_missing_on_secret_task",
		"severity": "high",
		"category": "security",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"context": listed,
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' passes %v without no_log — the rendered value is printed and logged.", [ans.name_of(task), listed]),
	}
}
