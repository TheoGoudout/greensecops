# METADATA
# title: Registry credentials written into the workflow
# description: "A job container: or services: entry carries a credentials: block whose password is a literal rather than a secret reference. Registry credentials in the file are readable by anyone who can read the repository, are copied into every fork, and stay in git history after the line is deleted — and a registry password usually grants push as well as pull, so the leak is write access to the images the pipeline consumes."
# custom:
#   severity: critical
#   severity_weight: 3.5
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           container:
#             image: private.registry.example.com/app:1
#             credentials:
#               username: ci
#               password: hunter2-real-registry-password
#           steps:
#             - run: npm test
#     good: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           container:
#             image: private.registry.example.com/app:1
#             credentials:
#               username: ci
#               password: ${{ secrets.REGISTRY_PASSWORD }}
#           steps:
#             - run: npm test
#     fix: |
#       Move the password to a repository or environment secret and reference it with ${{ secrets.NAME }}, then rotate it — a credential that has been committed is compromised from the push that added it, and deleting the line does not remove it from history.
package greensecops.ci_workflow.security.hardcoded_container_credentials

import data.greensecops.lib.workflow as wf
import rego.v1

_literal_password(credentials) := password if {
	password := credentials.password
	is_string(password)
	password != ""
	not wf.is_expression(password)
}

violations contains violation if {
	some job_name, job in input.jobs
	_literal_password(job.container.credentials)

	violation := {
		"rule": "hardcoded_container_credentials",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' gives its container a literal registry password. Use ${{ secrets.NAME }} and rotate the value — it is in git history from the commit that added it.", [job_name]),
		"context": "container.credentials.password",
		"discriminator": sprintf("%v:container", [job_name]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some service_name, service in job.services
	_literal_password(service.credentials)

	violation := {
		"rule": "hardcoded_container_credentials",
		"severity": "critical",
		"category": "security",
		"job": job_name,
		"message": sprintf("Service '%v' in job '%v' has a literal registry password. Use ${{ secrets.NAME }} and rotate the value.", [service_name, job_name]),
		"context": "services.credentials.password",
		"discriminator": sprintf("%v:service:%v", [job_name, service_name]),
	}
}
