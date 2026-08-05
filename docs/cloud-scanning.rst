Connecting an AWS account
=========================

Cloud posture scanning reads a connected account through a role you create and
GreenSecOps assumes. It is read-only by construction: no static access keys are
accepted or stored (see ``CloudAccount``'s docstring), and the collector calls
only ``Describe``/``List``/``Get`` APIs.

The role
--------

Create a role in the account you want scanned whose trust policy allows
GreenSecOps to assume it, with the External ID shown on the cloud account card
after you add it. The External ID is what stops a third party who learns your
role ARN from assuming it — it is generated per account and never reused.

Permissions
-----------

AWS's managed **``SecurityAudit``** policy covers everything the scanner reads,
and is the simplest thing to attach. If you would rather grant exactly what is
used and nothing more, this is the full list:

.. code-block:: json

   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Resource": "*",
       "Action": [
         "cloudtrail:DescribeTrails",
         "cloudtrail:GetTrailStatus",
         "ec2:DescribeSecurityGroups",
         "ec2:DescribeVolumes",
         "ecr:DescribeRepositories",
         "eks:DescribeCluster",
         "eks:ListClusters",
         "elasticloadbalancing:DescribeListeners",
         "elasticloadbalancing:DescribeLoadBalancerAttributes",
         "elasticloadbalancing:DescribeLoadBalancers",
         "iam:GenerateCredentialReport",
         "iam:GetCredentialReport",
         "iam:GetPolicyVersion",
         "iam:ListMFADevices",
         "iam:ListPolicies",
         "iam:ListUsers",
         "kms:DescribeKey",
         "kms:GetKeyRotationStatus",
         "kms:ListKeys",
         "lambda:GetFunctionUrlConfig",
         "lambda:ListFunctions",
         "logs:DescribeLogGroups",
         "rds:DescribeDBInstances",
         "s3:GetBucketEncryption",
         "s3:GetBucketLogging",
         "s3:GetBucketPolicy",
         "s3:GetBucketPublicAccessBlock",
         "s3:GetBucketVersioning",
         "s3:ListAllMyBuckets",
         "secretsmanager:ListSecrets"
       ]
     }]
   }

A missing permission costs findings, never the scan
---------------------------------------------------

Each resource type is collected independently. If the role cannot read one, the
scanner logs a warning, treats that type as empty, and carries on — a partial
picture is more useful than none, and the next scan picks the type up once the
permission is granted.

The cost of that design is worth stating plainly: **an under-permissioned role
produces fewer findings, not an error.** A clean report from a role missing
``s3:GetBucketPolicy`` does not mean no bucket is public; it means no bucket
policy was read. Rules are written to fire on a resource that is *present and
misconfigured* rather than on an empty list, precisely so that a permission gap
cannot manufacture findings either — but it can still hide them.

What is never read
------------------

- **No secret values.** ``secretsmanager:ListSecrets`` returns rotation
  configuration and never a payload; ``GetSecretValue`` is not called anywhere.
- **No Lambda environment values.** Only variable *names* are collected — the
  values are exactly what a rule wants to report as exposed, so storing them
  would recreate the problem.
- **No object contents.** S3 is read at the bucket-configuration level only.

Regions
-------

Regional services are queried in each region configured on the account.
CloudTrail is queried once, in the first configured region, because a single
call already returns multi-region trails. IAM and S3 are global.
