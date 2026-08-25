# METADATA
# title: apt cache refreshed on every run
# description: An apt task sets update_cache without cache_valid_time, so every run re-downloads the package indexes even when they were refreshed seconds earlier. On a fleet that is a large amount of transfer for no change.
# custom:
#   severity: low
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Install nginx
#         ansible.builtin.apt:
#           name: nginx
#           update_cache: true
#     good: |
#       - name: Install nginx
#         ansible.builtin.apt:
#           name: nginx
#           update_cache: true
#           cache_valid_time: 3600
#     fix: |
#       Add cache_valid_time (seconds) so the index is refreshed only when it is actually stale.
package greensecops.iac_ansible.energy.apt_cache_always_updated

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) == "ansible.builtin.apt"
	ans.truthy(ans.arg(task, "update_cache"))
	not ans.has_arg(task, "cache_valid_time")
	violation := {
		"rule": "apt_cache_always_updated",
		"severity": "low",
		"category": "energy",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' refreshes the apt cache with no cache_valid_time — the package indexes are re-downloaded on every run.", [ans.name_of(task)]),
	}
}
