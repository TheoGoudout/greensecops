# METADATA
# title: File mode grants write to everyone
# description: A file, copy, template or directory task sets a mode whose "other" bits include write, so any local account can alter the contents. For a script, a unit file or a configuration file that is a privilege-escalation path.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Install the entrypoint
#         ansible.builtin.copy:
#           src: entrypoint.sh
#           dest: /usr/local/bin/entrypoint
#           mode: "0777"
#     good: |
#       - name: Install the entrypoint
#         ansible.builtin.copy:
#           src: entrypoint.sh
#           dest: /usr/local/bin/entrypoint
#           mode: "0755"
#     fix: |
#       Drop the world-write bit — 0755 for something executable, 0644 for data, 0600 where only the owner should read it.
package greensecops.iac_ansible.security.world_writable_mode

import data.greensecops.lib.ansible as ans
import rego.v1

# Octal, three or four digits, whose last digit carries the write bit (2, 3, 6
# or 7). Quoted in practice, because Ansible warns about unquoted modes.
_world_writable(mode) if {
	is_string(mode)
	regex.match(`^0?[0-7][0-7][2367]$`, mode)
}

# Symbolic: o+w or a+w, in any of the orders chmod accepts.
_world_writable(mode) if {
	is_string(mode)
	regex.match(`[oa][ugoa]*\+[rx]*w`, mode)
}

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	mode := ans.arg(task, "mode")
	not ans.is_templated(mode)
	_world_writable(mode)
	violation := {
		"rule": "world_writable_mode",
		"severity": "high",
		"category": "security",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"context": mode,
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' sets mode %v — every local account can write to it.", [ans.name_of(task), mode]),
	}
}
