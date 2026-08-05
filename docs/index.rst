GreenSecOps
===========

GreenSecOps grades your software delivery pipeline across six analysis engines, sharing one
Rego-rule catalog and one grading model:

- **CI Workflow** — static analysis of GitHub Actions YAML across five categories: security,
  reliability, performance, maintainability, and energy efficiency.
- **CI Telemetry** — dynamic analysis of measured runtime data (runner sizing, memory/disk
  pressure) from completed workflow runs.
- **Terraform** — static analysis of ``.tf``/``.tf.json`` files in any configured folder of a
  repository, before they're ever applied.
- **AWS Cloud Posture** — live scanning of a connected AWS account (read-only, via
  ``sts:AssumeRole``) across S3, IAM, security groups, RDS, EBS, Lambda, CloudTrail,
  CloudWatch Logs, EKS, ECR, load balancers, Secrets Manager and KMS. See
  :doc:`cloud-scanning` for the role and permissions it needs.
- **Docker & Compose** — static analysis of Dockerfiles and Compose files anywhere in a
  repository, covering container privilege, image pinning, layer-cache efficiency and image
  size.
- **Docker Runtime** — dynamic analysis of measured build and container telemetry (layer
  cache-hit ratio, image and context size, OOM kills, health state), reported by the companion
  GitHub Action.

See :doc:`rules/index` for the full rule catalog, and :doc:`rule-authoring` for how to add
to it — including what each engine's rules can see, and where the collectors run out of
signal. Each engine's scan/finding lifecycle is documented alongside the source in
``docs/state-machines.md``.

.. toctree::
   :maxdepth: 2

   reference
   rules/index
   rule-authoring
   cloud-scanning
