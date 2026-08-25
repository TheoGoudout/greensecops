# METADATA
# title: Service started but not enabled
# description: A service task that sets state=started without enabled leaves the unit running now and absent after a reboot. An instance that is replaced or restarted comes back without it, which is the failure mode that only shows up when something else has already gone wrong.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Start Docker
#         ansible.builtin.systemd_service:
#           name: docker
#           state: started
#     good: |
#       - name: Start Docker
#         ansible.builtin.systemd_service:
#           name: docker
#           state: started
#           enabled: true
#     fix: |
#       Add enabled: true so the unit survives a reboot, or say enabled: false explicitly if it genuinely should not.
package greensecops.iac_ansible.reliability.service_not_enabled

import data.greensecops.lib.ansible as ans
import rego.v1

_service_modules := {
	"ansible.builtin.service",
	"ansible.builtin.systemd",
	"ansible.builtin.systemd_service",
	"ansible.builtin.sysvinit",
}

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.module(task) in _service_modules

	# Only `started` implies a lasting intent. A handler that restarts a unit is
	# reacting to a config change, not declaring how the host should boot.
	ans.arg(task, "state") == "started"
	not ans.has_arg(task, "enabled")
	violation := {
		"rule": "service_not_enabled",
		"severity": "medium",
		"category": "reliability",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' starts a service without enabling it — it will not come back after a reboot.", [ans.name_of(task)]),
	}
}
