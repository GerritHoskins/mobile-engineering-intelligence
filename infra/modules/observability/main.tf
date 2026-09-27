# How failures surface: CloudWatch alarms and an ingestion-failure rule, all
# notifying one SNS topic (email), plus a dashboard. Traces go to X-Ray via the
# ADOT sidecar (modules/service).

locals {
  alarm_actions = [aws_sns_topic.alerts.arn]
  llm_metric    = "LlmErrors"
  namespace     = "MEI/${var.name}"
}

resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

# Confirm the subscription from the email AWS sends; until then nothing is delivered.
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

data "aws_iam_policy_document" "alerts" {
  statement {
    sid       = "EventBridgeIngestionFailures"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.ingestion_failed.arn]
    }
  }

  statement {
    sid       = "CloudWatchAlarms"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts.json
}

# ---------- API ----------

resource "aws_cloudwatch_metric_alarm" "api_down" {
  alarm_name          = "${var.name}-api-down"
  alarm_description   = "No healthy API task behind the load balancer (/healthz failing or service at 0)."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name}-api-5xx"
  alarm_description   = "The API answered with server errors."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.target_group_arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

# app.observability logs "<METHOD> <route template> <status> <ms>ms" per request.
resource "aws_cloudwatch_log_metric_filter" "llm_errors" {
  name           = "${var.name}-llm-errors"
  log_group_name = var.log_group_name
  # 500 = misconfigured (wrong workspace id, missing IAM action); 502/503 = model side.
  pattern = "[method, route=\"*/summary\" || route=\"*/narrative\", status=500 || status=502 || status=503, latency]"

  metric_transformation {
    name          = local.llm_metric
    namespace     = local.namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "llm_errors" {
  alarm_name          = "${var.name}-llm-errors"
  alarm_description   = "Release summaries or reproduction narratives failed (model unavailable, refused, or ungrounded output)."
  namespace           = local.namespace
  metric_name         = local.llm_metric
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

# ---------- database ----------

resource "aws_cloudwatch_metric_alarm" "db_cpu" {
  alarm_name          = "${var.name}-db-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = var.db_instance_id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 80
  alarm_actions       = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${var.name}-db-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = var.db_instance_id }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "LessThanThreshold"
  threshold           = 2 * 1024 * 1024 * 1024 # bytes
  alarm_actions       = local.alarm_actions
}

# ---------- ingestion ----------

resource "aws_cloudwatch_metric_alarm" "schedule_errors" {
  alarm_name          = "${var.name}-ingestion-not-started"
  alarm_description   = "EventBridge Scheduler could not start the ingestion task (RunTask failed or was dropped)."
  namespace           = "AWS/Scheduler"
  metric_name         = "TargetErrorCount"
  dimensions          = { ScheduleGroup = var.schedule_group_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
}

# The task exited non-zero (vendor API error, bad credentials, ...) or never
# started at all (an empty vendor secret, an image that won't pull): the latter
# has no container exit code, so it needs its own branch.
resource "aws_cloudwatch_event_rule" "ingestion_failed" {
  name        = "${var.name}-ingestion-failed"
  description = "Ingestion task stopped with a non-zero exit code"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [var.cluster_arn]
      lastStatus = ["STOPPED"]
      group      = ["family:${var.jobs_family}"]
      "$or" = [
        { containers = { exitCode = [{ "anything-but" = 0 }] } },
        { stopCode = ["TaskFailedToStart"] },
      ]
    }
  })
}

resource "aws_cloudwatch_event_target" "ingestion_failed" {
  rule = aws_cloudwatch_event_rule.ingestion_failed.name
  arn  = aws_sns_topic.alerts.arn

  input_transformer {
    input_paths = {
      reason = "$.detail.stoppedReason"
      task   = "$.detail.taskArn"
    }
    input_template = "\"Ingestion task <task> failed: <reason>. Logs: CloudWatch ${var.log_group_name}, stream prefix job/.\""
  }
}

# ---------- dashboard ----------

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = var.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "API requests and errors"
          region = var.region
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", "TargetGroup", var.target_group_arn_suffix],
            [".", "HTTPCode_Target_4XX_Count", ".", ".", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "API latency (p50 / p95)"
          region = var.region
          period = 300
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, { stat = "p50" }],
            ["...", { stat = "p95" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 8, height = 6
        properties = {
          title   = "Healthy API tasks"
          region  = var.region
          stat    = "Minimum"
          period  = 60
          metrics = [["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix]]
        }
      },
      {
        type = "metric", x = 8, y = 6, width = 8, height = 6
        properties = {
          title   = "LLM errors"
          region  = var.region
          stat    = "Sum"
          period  = 300
          metrics = [[local.namespace, local.llm_metric]]
        }
      },
      {
        type = "metric", x = 16, y = 6, width = 8, height = 6
        properties = {
          title  = "Ingestion schedule"
          region = var.region
          stat   = "Sum"
          period = 3600
          metrics = [
            ["AWS/Scheduler", "InvocationAttemptCount", "ScheduleGroup", var.schedule_group_name],
            [".", "TargetErrorCount", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 12, height = 6
        properties = {
          title  = "Database"
          region = var.region
          period = 300
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", var.db_instance_id, { stat = "Average" }],
            [".", "DatabaseConnections", ".", ".", { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
    ]
  })
}
