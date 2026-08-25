# METADATA
# title: Package installed with state latest
# description: A package task uses state=latest, which re-resolves the package index and reinstalls on every run even when nothing changed. That is repeated download and CPU for no change in outcome, and it makes the run non-reproducible.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Install nginx
#         ansible.builtin.apt:
#           name: nginx
#           state: latest
#     good: |
#       - name: Install nginx
#         ansible.builtin.apt:
#           name: nginx
#           state: present
#     fix: |
#       Use state: present, and pin the version explicitly when a specific one is required.
package greensecops.iac_ansible.energy.package_state_latest

import data.greensecops.lib.ansible as ans
import rego.v1

_package_modules := {
	"ansible.builtin.apt",
	"ansible.builtin.dnf",
	"ansible.builtin.yum",
	"ansible.builtin.package",
	"ansible.builtin.pip",
	"community.general.apk",
	"community.general.pacman",
	"community.general.zypper",
}

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) in _package_modules
	ans.arg(task, "state") == "latest"
	violation := {
		"rule": "package_state_latest",
		"severity": "medium",
		"category": "energy",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' installs with state=latest — every run re-resolves and may reinstall the package.", [ans.name_of(task)]),
	}
}
