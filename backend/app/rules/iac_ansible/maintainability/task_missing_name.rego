# METADATA
# title: Task with no name
# description: An unnamed task shows up in output as its module and arguments, so a failure names the module rather than the intent, and --start-at-task cannot address it. The name is also what a reader uses to tell two similar tasks apart.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       - ansible.builtin.file:
#           path: /opt/app
#           state: directory
#     good: |
#       - name: Create the application directory
#         ansible.builtin.file:
#           path: /opt/app
#           state: directory
#     fix: |
#       Add name: describing what the task achieves, phrased as the outcome rather than the mechanism.
package greensecops.iac_ansible.maintainability.task_missing_name

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.name_of(task) == ""
	violation := {
		"rule": "task_missing_name",
		"severity": "low",
		"category": "maintainability",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": "",
		"context": ans.module(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("An unnamed %v task — output and --start-at-task have nothing to call it.", [ans.short_module(task)]),
	}
}
