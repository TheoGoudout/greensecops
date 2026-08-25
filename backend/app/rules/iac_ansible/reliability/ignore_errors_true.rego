# METADATA
# title: Task ignores every error
# description: ignore_errors makes the play continue past any failure of the task, including failures nobody anticipated. Later tasks then run against a host in an unknown state, and the deploy reports success. failed_when says which failures are acceptable and leaves the rest fatal.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Remove the old unit file
#         ansible.builtin.command: rm /etc/systemd/system/old.service
#         ignore_errors: true
#     good: |
#       - name: Remove the old unit file
#         ansible.builtin.file:
#           path: /etc/systemd/system/old.service
#           state: absent
#     fix: |
#       Replace ignore_errors with failed_when naming the condition that is genuinely acceptable, or use a module that is already idempotent about absence.
package greensecops.iac_ansible.reliability.ignore_errors_true

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.truthy(object.get(task, "ignore_errors", false))
	violation := {
		"rule": "ignore_errors_true",
		"severity": "medium",
		"category": "reliability",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' sets ignore_errors: true — every failure is swallowed, including ones nobody anticipated.", [ans.name_of(task)]),
	}
}
