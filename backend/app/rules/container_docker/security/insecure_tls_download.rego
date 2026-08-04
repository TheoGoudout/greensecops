# METADATA
# title: Certificate verification disabled while fetching
# description: A RUN instruction disables TLS certificate verification — curl -k, wget --no-check-certificate, pip --trusted-host, or npm strict-ssl false. Whatever is fetched is then accepted from whoever answers, and it is being baked into the image, so a single successful interception during any build ships a compromised artifact to everywhere the image runs. The usual cause is a corporate TLS-inspecting proxy, which is fixed by installing its CA rather than by turning verification off.
# custom:
#   severity: high
#   detection: pattern_matching
#   examples:
#     bad: |
#       FROM python:3.12-slim
#       RUN pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org requests
#     good: |
#       FROM python:3.12-slim
#       RUN pip install requests
#     fix: |
#       Remove the flag. If the build sits behind a TLS-inspecting proxy, install that proxy's CA certificate into the image's trust store instead, so verification still happens against a certificate you control.
package greensecops.container_docker.security.insecure_tls_download

import rego.v1

_command_text(inst) := concat("\n", [part |
	some key in ["value", "heredoc"]
	part := object.get(inst, key, "")
	is_string(part)
	part != ""
])

# Each pattern is anchored on the tool as well as the flag: `-k` alone is far
# too common a short option to match on its own, and `--trusted-host` is only
# meaningful to pip.
_insecure_patterns := [
	`(?i)\b(curl|wget)\b[^\n]*\s(-k|--insecure)\b`,
	`(?i)\bwget\b[^\n]*\s--no-check-certificate\b`,
	`(?i)\bpip3?\b[^\n]*\s--trusted-host\b`,
	`(?i)\bnpm\b[^\n]*\sstrict-ssl[\s=]+false\b`,
	`(?i)\bgit\b[^\n]*\shttp\.sslverify[\s=]+false\b`,
	`(?i)\bexport\s+(NODE_TLS_REJECT_UNAUTHORIZED|PYTHONHTTPSVERIFY)\s*=\s*0\b`,
]

_disables_verification(text) if {
	some pattern in _insecure_patterns
	regex.match(pattern, text)
}

violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "RUN"
	text := _command_text(inst)
	_disables_verification(text)

	violation := {
		"rule": "insecure_tls_download",
		"severity": "high",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "TLS certificate verification is disabled for this download, so its content is accepted from whoever answers — and it is baked into the image. Install the needed CA certificate instead of skipping the check.",
		"context": substring(text, 0, 300),
		"discriminator": text,
	}
}

# ENV is the other half of the same pattern: setting the variable once at the
# top disables verification for every later instruction *and* at runtime.
violations contains violation if {
	some df in input.dockerfiles
	some inst in df.instructions
	inst.instruction == "ENV"
	regex.match(`(?i)\b(NODE_TLS_REJECT_UNAUTHORIZED|PYTHONHTTPSVERIFY)\b\s*[= ]\s*["']?0`, inst.value)

	violation := {
		"rule": "insecure_tls_download",
		"severity": "high",
		"category": "security",
		"file_path": object.get(df, "__docker_file", ""),
		"line_start": object.get(inst, "__start_line__", null),
		"line_end": object.get(inst, "__end_line__", null),
		"message": "This ENV disables TLS certificate verification for every later build step and at runtime too. Install the needed CA certificate instead.",
		"context": inst.value,
		"discriminator": inst.value,
	}
}
