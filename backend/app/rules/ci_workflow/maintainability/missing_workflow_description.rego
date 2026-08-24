# METADATA
# title: Workflow has no name
# description: "The workflow has no top-level name, so the Actions sidebar and the checks list identify it by file path. A name is the one place a reader learns what the file is for before opening it. Jobs and steps are deliberately out of scope: GitHub falls back to the job key, which is the identifier people already write needs: edges against and is usually a better name than a prose one, and an unnamed step shows its run command, which is clearer still."
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
		"message": "Workflow has no top-level 'name' field, so runs are listed by file path. Add a descriptive name.",
		"context": null,
		"discriminator": "workflow",
	}
}

# The second clause reported every job without a `name:`, which is most jobs in
# most repositories — GitHub falls back to the job key, which is usually a fine
# name and is the one people write the `needs:` edges against. One `info`
# finding per job for a convention nobody follows is noise, and it was filed
# under a slug about the *workflow* having no description.
