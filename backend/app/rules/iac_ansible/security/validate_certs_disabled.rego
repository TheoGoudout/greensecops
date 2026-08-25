# METADATA
# title: TLS verification turned off
# description: A task sets validate_certs to false, so the transfer accepts any certificate and anyone on the path can serve a substitute. Whatever is fetched is then installed or acted on as if it were authentic.
# custom:
#   severity: high
#   detection: static_analysis
#   examples:
#     bad: |
#       - name: Fetch the release
#         ansible.builtin.get_url:
#           url: https://internal.example.com/app.tar.gz
#           dest: /tmp/app.tar.gz
#           validate_certs: false
#     good: |
#       - name: Fetch the release
#         ansible.builtin.get_url:
#           url: https://internal.example.com/app.tar.gz
#           dest: /tmp/app.tar.gz
#     fix: |
#       Remove validate_certs: false. If the host presents a private CA, install that CA on the managed node and leave verification on.
package greensecops.iac_ansible.security.validate_certs_disabled

import data.greensecops.lib.ansible as ans
import rego.v1

violations contains violation if {
	some f in input.files
	some task in ans.tasks_of(f)
	ans.falsy(ans.arg(task, "validate_certs"))
	violation := {
		"rule": "validate_certs_disabled",
		"severity": "high",
		"category": "security",
		"file_path": ans.path(f),
		"line_start": ans.line(task),
		"line_end": ans.end_line(task),
		"task_name": ans.name_of(task),
		"discriminator": ans.discriminator(task),
		"message": sprintf("Task '%v' disables TLS verification — the transfer accepts any certificate.", [ans.name_of(task)]),
	}
}
