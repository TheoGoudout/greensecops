# METADATA
# title: Package module driven by a loop
# description: A package module is invoked once per loop item, so N packages mean N transactions — N index reads, N dependency resolutions and N scriptlet runs. Every package module accepts a list for name, which does the same work in one transaction.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Install base packages
#         ansible.builtin.dnf:
#           name: "{{ item }}"
#           state: present
#         loop:
#           - jq
#           - curl
#     good: |
#       - name: Install base packages
#         ansible.builtin.dnf:
#           name:
#             - jq
#             - curl
#           state: present
#     fix: |
#       Pass the list to name: and drop the loop. The module resolves and installs them in one transaction.
package greensecops.iac_ansible.energy.package_module_in_loop

import data.greensecops.lib.ansible as ans
import rego.v1

_package_modules := {
	"ansible.builtin.apt",
	"ansible.builtin.dnf",
	"ansible.builtin.yum",
	"ansible.builtin.package",
	"community.general.apk",
	"community.general.pacman",
	"community.general.zypper",
}

_loop_keys := {"loop", "with_items", "with_list", "with_flattened"}

_looping(task) if {
	some key in _loop_keys
	_ = task[key]
}

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) in _package_modules
	_looping(task)
	violation := {
		"rule": "package_module_in_loop",
		"severity": "medium",
		"category": "energy",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' loops a package module — one transaction per item where the module accepts the whole list at once.", [ans.name_of(task)]),
	}
}
