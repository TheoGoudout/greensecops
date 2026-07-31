# One launch template + Auto Scaling group per GreenSecOps service. Every
# service gets its own group even when it is pinned to a single instance, so
# scaling a role up later is a variable change rather than a rewrite, and a
# failed instance is replaced without intervention.

locals {
  name = "${var.name_prefix}-${var.role}"

  tags = merge(var.tags, {
    Name               = local.name
    "greensecops:role" = var.role

    # Ansible's dynamic inventory groups on the role; the service list tells
    # the deploy which containers this group is responsible for.
    "greensecops:services" = join(",", var.services)
  })
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/greensecops/${var.name_prefix}/${var.role}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = local.tags
}

resource "aws_launch_template" "this" {
  name_prefix   = "${local.name}-"
  image_id      = var.ami_id
  instance_type = var.instance_type
  user_data     = base64encode(var.user_data)

  # Security groups live in the interface block rather than at the top level:
  # the two forms conflict, and assigning a public address needs this form.
  # A public address is how a host with no NAT gateway reaches ECR, GitHub and
  # the LLM providers — inbound is still closed by the security group.
  network_interfaces {
    associate_public_ip_address = var.assign_public_ip
    security_groups             = var.security_group_ids
    delete_on_termination       = true
  }

  iam_instance_profile {
    name = var.instance_profile_name
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = var.root_volume_size
      volume_type           = "gp3"
      encrypted             = true
      kms_key_id            = var.kms_key_arn
      delete_on_termination = true
    }
  }

  metadata_options {
    # IMDSv2 only: a server-side request forgery in the application can't be
    # used to read the instance role's credentials without a PUT first.
    http_tokens                 = "required"
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "enabled"
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags          = local.tags
  }

  tag_specifications {
    resource_type = "volume"
    tags          = local.tags
  }

  tags = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "this" {
  name                = local.name
  vpc_zone_identifier = var.subnet_ids

  min_size         = var.min_size
  max_size         = var.max_size
  desired_capacity = var.desired_capacity

  target_group_arns = var.target_group_arns

  # A service behind a load balancer is only healthy once the load balancer
  # agrees; one with no target group can only be judged by EC2 status checks.
  health_check_type         = length(var.target_group_arns) > 0 ? "ELB" : "EC2"
  health_check_grace_period = var.health_check_grace_period

  capacity_rebalance    = true
  protect_from_scale_in = false

  launch_template {
    id      = aws_launch_template.this.id
    version = aws_launch_template.this.latest_version
  }

  instance_refresh {
    strategy = "Rolling"

    preferences {
      # Never drop below the current capacity while replacing instances; a
      # single-instance group briefly runs two.
      min_healthy_percentage = 100
      instance_warmup        = var.health_check_grace_period
    }
  }

  dynamic "tag" {
    for_each = local.tags

    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  lifecycle {
    create_before_destroy = true

    # Once a scaling policy owns capacity, re-applying Terraform must not drag
    # the group back to its seed value.
    ignore_changes = [desired_capacity]
  }
}

resource "aws_autoscaling_policy" "target_tracking" {
  count = var.autoscaling == null ? 0 : 1

  name                      = "${local.name}-target-tracking"
  autoscaling_group_name    = aws_autoscaling_group.this.name
  policy_type               = "TargetTrackingScaling"
  estimated_instance_warmup = var.health_check_grace_period

  target_tracking_configuration {
    target_value = var.autoscaling.target_value

    dynamic "predefined_metric_specification" {
      for_each = var.autoscaling.metric == "cpu" ? [1] : []

      content {
        predefined_metric_type = "ASGAverageCPUUtilization"
      }
    }

    dynamic "predefined_metric_specification" {
      for_each = var.autoscaling.metric == "requests" ? [1] : []

      content {
        predefined_metric_type = "ALBRequestCountPerTarget"

        # CloudWatch addresses this metric by "<lb-arn-suffix>/<tg-arn-suffix>",
        # for which both load balancer and target group expose an attribute.
        resource_label = "${var.alb_arn_suffix}/${var.target_group_arn_suffix}"
      }
    }

    disable_scale_in = false
  }
}
