package greensecops.container_docker.security.secret_file_copied_test

import data.greensecops.container_docker.security.secret_file_copied
import rego.v1

_df(instructions) := {"dockerfiles": [{
	"__docker_file": "Dockerfile",
	"final_stage": 0,
	"stages": [{"index": 0, "name": null, "is_final": true, "__start_line__": 1, "__end_line__": 9}],
	"instructions": instructions,
}]}

_copy(value, flags) := {
	"instruction": "COPY",
	"value": value,
	"flags": flags,
	"stage": 0,
	"heredoc": null,
	"__start_line__": 4,
	"__end_line__": 4,
}

test_violation_for_an_npmrc if {
	violations := secret_file_copied.violations with input as _df([_copy(".npmrc /root/.npmrc", {})])
	count(violations) == 1
	some v in violations
	v.discriminator == ".npmrc"
}

test_violation_for_an_ssh_private_key if {
	violations := secret_file_copied.violations with input as _df([_copy("keys/id_rsa /root/.ssh/id_rsa", {})])
	count(violations) == 1
}

test_violation_for_a_pem_file if {
	violations := secret_file_copied.violations with input as _df([_copy("certs/client.pem /etc/ssl/client.pem", {})])
	count(violations) == 1
}

test_violation_for_an_ssh_directory if {
	violations := secret_file_copied.violations with input as _df([_copy(".ssh /root/.ssh", {})])
	count(violations) == 1
}

test_violation_for_an_aws_credentials_directory if {
	violations := secret_file_copied.violations with input as _df([_copy(".aws/ /root/.aws/", {})])
	count(violations) == 1
}

test_violation_for_a_gcp_service_account_json if {
	violations := secret_file_copied.violations with input as _df([_copy("service_account.json /app/sa.json", {})])
	count(violations) == 1
}

test_violation_for_add_as_well_as_copy if {
	violations := secret_file_copied.violations with input as _df([{
		"instruction": "ADD",
		"value": "id_ed25519 /root/.ssh/id_ed25519",
		"flags": {},
		"stage": 0,
		"heredoc": null,
		"__start_line__": 4,
		"__end_line__": 4,
	}])
	count(violations) == 1
}

test_no_violation_for_ordinary_sources if {
	violations := secret_file_copied.violations with input as _df([_copy("package.json package-lock.json ./", {})])
	count(violations) == 0
}

# The destination is not a source. A build that writes an .npmrc it generated
# from a secret mount is not copying a credential in.
test_no_violation_when_only_the_destination_looks_like_a_secret if {
	violations := secret_file_copied.violations with input as _df([_copy("config/registry.conf /root/.npmrc", {})])
	count(violations) == 0
}

# COPY --from=builder moves a file between stages of this build rather than
# reaching into the build context.
test_no_violation_for_a_cross_stage_copy if {
	violations := secret_file_copied.violations with input as _df([_copy("/build/client.pem /etc/ssl/client.pem", {"from": "builder"})])
	count(violations) == 0
}

test_no_violation_for_a_single_token_value if {
	violations := secret_file_copied.violations with input as _df([_copy(".npmrc", {})])
	count(violations) == 0
}

test_each_secret_source_is_its_own_finding if {
	violations := secret_file_copied.violations with input as _df([_copy(".npmrc id_rsa /root/", {})])
	count(violations) == 2
	count({v.discriminator | some v in violations}) == 2
}
