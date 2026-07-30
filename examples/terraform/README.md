# Terraform examples

Real-world Terraform modules used to prove the `iac_terraform` OPA rules fire
(and stay quiet) on realistic configuration — the Terraform counterpart to the
GitHub Actions examples one level up (`examples/deploy.yml` /
`examples/deploy-insecure.yml`).

Each module is parsed and merged exactly as production does
(`backend/app/services/terraform/hcl_parser.py::merge_terraform_configs`) and
evaluated against the live rule suite by
[`scripts/validate_terraform_examples.py`](../../scripts/validate_terraform_examples.py),
which runs in CI (`.github/workflows/opa.yml`). The set of rules a module trips
must match its `expected.yaml` **exactly**, so a rule that regresses (stops
firing) or starts producing a false positive fails the build.

## Adding a new example (no code required)

1. Create a folder here, named for the scenario (e.g. `aws-lambda-api/`).
2. Drop in one or more `.tf` (or `.tf.json`) files. They are treated as a
   single Terraform root module — resources in one file can reference variables
   in another, just like a real directory.
3. Add an `expected.yaml` listing the rule slugs the module should trip:

   ```yaml
   violations:
     - open_ingress_security_group
     - unencrypted_ebs_volume
   ```

   Use `violations: []` for a clean module that must stay violation-free across
   the whole suite.

That's it — the validator auto-discovers every folder. No Python, workflow, or
manifest changes needed.

Note that these fixtures assert an *exact* expected set, because several exist
precisely to demonstrate a finding. The project's own AWS deployment config is
held to a stricter bar by a separate check — `scripts/validate_deploy_terraform.py`
fails on **any** violation under `deploy/terraform/`. See
[`deploy/README.md`](../../deploy/README.md).

Run it locally with:

```bash
pip install "python-hcl2>=6.1,<7.0" "ruamel.yaml>=0.18,<0.19"
python scripts/validate_terraform_examples.py
```

(`opa` must be on `PATH`, or set `OPA_BIN` to its location.)

## Rule slugs

The slug is the `.rego` file name (without extension) under
`backend/app/rules/iac_terraform/`. Current rules:

| Slug | Catches |
| --- | --- |
| `s3_bucket_public_acl` | S3 bucket with a `public-read` / `public-read-write` ACL |
| `s3_bucket_missing_versioning` | S3 bucket with neither an inline `versioning` block nor a companion `aws_s3_bucket_versioning` resource |
| `resource_missing_tags` | A taggable resource (s3, instance, sg, vpc, subnet, db, lambda, ebs) with no `tags` |
| `variable_missing_description` | A `variable` block with no `description` |
| `open_ingress_security_group` | Security-group ingress from `0.0.0.0/0` |
| `unencrypted_ebs_volume` | `aws_ebs_volume` without `encrypted = true` |
| `rds_not_encrypted` | `aws_db_instance` without `storage_encrypted = true` |
| `hardcoded_credentials_in_tf` | A literal `AKIA…` AWS access-key ID in an attribute |

## Current examples

| Folder | Story | Trips |
| --- | --- | --- |
| `aws-s3-static-site/` | "Before": a public static-site bucket | public ACL, no versioning, no tags |
| `aws-rds-postgres/` | "Before": a quickly-wired Postgres instance | unencrypted at rest, no tags, an undescribed variable |
| `aws-ec2-web/` | "Before": a tagged but insecure web tier | world-open ingress, unencrypted EBS, hardcoded key |
| `aws-s3-hardened/` | "After": the hardened bucket | *(nothing — clean)* |
| `aws-s3-split-config/` | "After", written for a modern provider: bucket config split into `aws_s3_bucket_versioning` and friends | *(nothing — clean)* |
