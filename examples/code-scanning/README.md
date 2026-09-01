# GreenSecOps in GitHub Code Scanning

One workflow per engine. Each one asks GreenSecOps to re-scan the repository,
fetches the result as SARIF, and uploads it — so the findings appear in the
repository's **Security → Code scanning** tab and inline on pull requests,
beside whatever else that repository already scans with.

| Workflow | Publishes |
|---|---|
| [`workflow.yml`](workflow.yml) | GitHub Actions workflow files |
| [`terraform.yml`](terraform.yml) | Terraform configuration |
| [`docker.yml`](docker.yml) | Dockerfiles and Compose files |
| [`ansible.yml`](ansible.yml) | Ansible playbooks and roles |

Copy the ones you want into `.github/workflows/`. They are independent; a
repository with no Terraform simply does not need `terraform.yml`.

## What you have to configure

Nothing, on the hosted service. Set the `GREENSECOPS_URL` **repository
variable** if you run your own instance.

There is no API key and no secret. The workflow authenticates with the
[OIDC token][oidc] GitHub mints for the run, which names the repository it
belongs to and expires with it — so a run can only ever ask about its own
repository, and there is no credential in the repository to leak or rotate.

That is what the two permissions are for:

```yaml
permissions:
  id-token: write        # mint the OIDC token
  security-events: write # upload the SARIF results
```

The repository still has to be registered with GreenSecOps — the analysis runs
there, and these workflows only publish what it found.

## Why one category per engine

Each workflow uploads under its own `category:`. GitHub treats a category as a
stream of results and closes any alert missing from the newest upload, so two
engines sharing a category would take turns closing each other's alerts.

## Why there is no `cloud.yml`

The cloud engine grades live resources in a connected AWS account, not files in
the checkout. A Code Scanning alert has to point at a line in the repository,
and there is nothing there to point at — those findings stay in the dashboard.

## Why the workflow sleeps

Analysis is asynchronous: the `POST` queues it and returns immediately. The
`sleep` gives the workers time to finish, so the report reflects this commit
rather than the previous scan. Raise it for a large repository; there is no
harm in fetching early beyond publishing slightly stale findings, which the
next run corrects.

[oidc]: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect
