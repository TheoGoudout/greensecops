# METADATA
# title: Missing name on the workflow or a job
# description: "The workflow or one of its jobs has no name, so the Actions UI and the checks list fall back to the file path and the job key. Steps are deliberately out of scope — an unnamed step shows its run command, which is usually clearer than a name would be, and reporting every one of them would bury the two places a name actually helps."
# custom:
#   severity: info
#   detection: static_analysis
#   examples:
#     bad: |
#       on:
#         push:
#           branches: [main]
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     good: |
#       name: CI
#       on:
#         push:
#           branches: [main]
#       jobs:
#         build:
#           name: Build application
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm run build
#     fix: |
#       Add a top-level name field to the workflow and a name field to each job. Descriptive names appear in the GitHub Actions UI and make CI logs easier to navigate.
package greensecops.ci_workflow.maintainability.missing_workflow_description

import rego.v1

violations contains violation if {
	not input.name
	violation := {
		"rule": "missing_workflow_description",
		"severity": "info",
		"category": "maintainability",
		"job": null,
		"message": "Workflow has no top-level 'name' field. Add a descriptive name to improve CI log readability.",
		"context": null,
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	not job.name
	violation := {
		"rule": "missing_workflow_description",
		"severity": "info",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Job '%v' has no 'name' field. Add a human-readable name to improve CI readability.", [job_name]),
		"context": null,
	}
}
