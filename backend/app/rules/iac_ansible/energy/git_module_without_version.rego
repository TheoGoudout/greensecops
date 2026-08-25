# METADATA
# title: git checkout with no version pinned
# description: A git task with no version always resolves the remote default branch, so it re-fetches whenever that branch moves and the run is not reproducible. Pinning a tag or commit lets the module skip the fetch when the working copy already matches.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Check out the application
#         ansible.builtin.git:
#           repo: https://github.com/example/app.git
#           dest: /opt/app
#     good: |
#       - name: Check out the application
#         ansible.builtin.git:
#           repo: https://github.com/example/app.git
#           dest: /opt/app
#           version: v2.4.1
#     fix: |
#       Add version: with a tag or commit SHA. A branch name is better than nothing but still moves.
package greensecops.iac_ansible.energy.git_module_without_version

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) == "ansible.builtin.git"
	not ans.has_arg(task, "version")
	violation := {
		"rule": "git_module_without_version",
		"severity": "medium",
		"category": "energy",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' checks out a git repository with no version — it re-fetches whenever the default branch moves.", [ans.name_of(task)]),
	}
}
