# METADATA
# title: Command task with no changed_when
# description: A command, shell, raw or script task reports "changed" every run unless it is told otherwise, so the play is never idempotent and every run looks like it altered the host. That hides real changes and makes handlers fire when nothing happened.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Read the cluster status
#         ansible.builtin.command: /usr/bin/cluster status
#     good: |
#       - name: Read the cluster status
#         ansible.builtin.command: /usr/bin/cluster status
#         changed_when: false
#     fix: |
#       Add changed_when: false for a read-only command, a real condition for one that may change something, or creates/removes so the module can decide for itself.
package greensecops.iac_ansible.reliability.command_without_changed_when

import data.greensecops.lib.ansible as ans
import rego.v1

# `creates` and `removes` let the module skip the command entirely, which is a
# stronger statement about idempotence than `changed_when` — a task that has
# one is not the failure this rule is about.
_self_guarding(task) if ans.has_arg(task, "creates")

_self_guarding(task) if ans.has_arg(task, "removes")

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.is_command(task)
	not ans.declares(task, "changed_when")
	not _self_guarding(task)
	violation := {
		"rule": "command_without_changed_when",
		"severity": "medium",
		"category": "reliability",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' runs %v with no changed_when, creates or removes — it reports changed on every run.", [ans.name_of(task), ans.short_module(task)]),
	}
}
