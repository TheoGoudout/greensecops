# METADATA
# title: Credential committed in a variables file
# description: A variables file assigns a credential-shaped name a literal value that is neither templated nor vaulted, so the secret is in git history for everyone with repository access. Rotating it means rewriting history, not changing a value.
# custom:
#   severity: critical
#   detection: pattern_matching
#   examples:
#     bad: |
#       postgres_password: S6xQ2vLm9TpKd4Rw8YnZ
#     good: |
#       postgres_password: "{{ lookup('amazon.aws.aws_ssm', '/app/secret/POSTGRES_PASSWORD') }}"
#     fix: |
#       Move the value into Ansible Vault or a secret store and reference it through a lookup or a vaulted variable, then rotate the credential that was committed.
package greensecops.iac_ansible.security.hardcoded_secret_in_vars

import data.greensecops.lib.ansible as ans
import data.greensecops.lib.workflow as wf
import rego.v1

# Worth reporting on sight because the format identifies it, or long and varied
# enough to be a real credential rather than a word. Both defer to the workflow
# library, which is where the corpus's value-shape tests already live.
_looks_secret(value) if wf.known_credential(value)

_looks_secret(value) if {
	wf.looks_high_entropy(value)
	not wf.is_placeholder(value)
}

violations contains violation if {
	some f in input.files
	vars := ans.vars_of(f)
	some name, value in vars
	not startswith(name, "__")
	ans.secret_name(name)
	ans.literal(value)
	_looks_secret(value)
	line := object.get(object.get(vars, "__lines__", {}), name, null)
	violation := {
		"rule": "hardcoded_secret_in_vars",
		"severity": "critical",
		"category": "security",
		"file_path": ans.path(f),
		"line_start": line,
		"line_end": line,
		"task_name": "",
		"discriminator": name,
		"message": sprintf("Variable '%v' holds a literal credential — it is in git history and cannot be rotated by editing it.", [name]),
	}
}
