# METADATA
# title: Remote archive unpacked on every run
# description: An unarchive task with remote_src and no creates re-downloads and re-extracts the archive on every run, because the module has nothing to test for existing output. That is the whole transfer and the whole extraction repeated for no change.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Install the toolchain
#         ansible.builtin.unarchive:
#           src: https://example.com/toolchain.tar.gz
#           dest: /opt
#           remote_src: true
#     good: |
#       - name: Install the toolchain
#         ansible.builtin.unarchive:
#           src: https://example.com/toolchain.tar.gz
#           dest: /opt
#           remote_src: true
#           creates: /opt/toolchain/bin/tc
#     fix: |
#       Add creates: pointing at a path the archive produces, so the task is a no-op once it has run.
package greensecops.iac_ansible.energy.unarchive_remote_src_without_creates

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) == "ansible.builtin.unarchive"
	ans.truthy(ans.arg(task, "remote_src"))
	not ans.has_arg(task, "creates")
	violation := {
		"rule": "unarchive_remote_src_without_creates",
		"severity": "low",
		"category": "energy",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' unpacks a remote archive with no creates — it re-downloads and re-extracts on every run.", [ans.name_of(task)]),
	}
}
