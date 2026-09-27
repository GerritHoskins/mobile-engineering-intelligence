locals {
  container_name = "api"
  # "none" keeps the first-pass task definition valid before any image exists;
  # desired_count is 0 until a real tag is supplied.
  image = "${aws_ecr_repository.this.repository_url}:${coalesce(var.image_tag, "none")}"
  # Claude Platform on AWS: IAM replaces the API key. Unset workspace = the LLM
  # endpoints answer 500 (misconfigured) while everything else works.
  llm_enabled = var.anthropic_aws_workspace_id != null
}

data "aws_caller_identity" "current" {}

# ---------- image registry ----------

resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # dev: destroy must not be blocked by pushed images

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ---------- security groups ----------

# CloudFront's origin-facing address ranges: the only clients the ALB accepts.
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "HTTP from CloudFront origin-facing ranges only"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_service" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.service.id
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
}

resource "aws_security_group" "service" {
  name        = "${var.name}-service"
  description = "Fargate tasks: reachable only from the ALB"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "service_from_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = var.container_port
  to_port                      = var.container_port
}

# Outbound via the NAT: ECR, Secrets Manager, CloudWatch, X-Ray, RDS, the
# vendor APIs (ingestion) and Claude Platform on AWS.
resource "aws_vpc_security_group_egress_rule" "service_all" {
  security_group_id = aws_security_group.service.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_vpc_security_group_ingress_rule" "db_from_service" {
  security_group_id            = var.db_security_group_id
  referenced_security_group_id = aws_security_group.service.id
  ip_protocol                  = "tcp"
  from_port                    = var.db_port
  to_port                      = var.db_port
}

# ---------- load balancer ----------

resource "aws_lb" "this" {
  name               = var.name
  load_balancer_type = "application"
  subnets            = var.public_subnet_ids
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "this" {
  name                 = var.name
  port                 = var.container_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 10

  health_check {
    path                = "/healthz" # liveness plus a database round trip
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Anything that reaches the ALB without CloudFront's secret header is refused,
# so the ALB's own DNS name can't be used to bypass the edge (and its IP allowlist).
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 1

  condition {
    http_header {
      http_header_name = var.origin_verify_header
      values           = [var.origin_verify_secret]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# ---------- IAM ----------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_db_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }
}

resource "aws_iam_role_policy" "execution_db_secret" {
  name   = "read-db-secret"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_db_secret.json
}

# The API's own AWS calls: Claude Platform on AWS (the one workspace) and
# X-Ray, via the ADOT sidecar. No vendor secrets: only ingestion needs those.
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid = "XRay"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
      "xray:GetSamplingStatisticSummaries",
    ]
    resources = ["*"] # X-Ray actions don't support resource-level permissions
  }

  dynamic "statement" {
    for_each = local.llm_enabled ? [1] : []

    content {
      sid = "ClaudePlatformOnAws"
      actions = [
        "aws-external-anthropic:CreateInference",
        "aws-external-anthropic:CountTokens",
        "aws-external-anthropic:GetModel",
        "aws-external-anthropic:GetWorkspace",
      ]
      resources = [
        "arn:aws:aws-external-anthropic:${var.region}:${data.aws_caller_identity.current.account_id}:workspace/${var.anthropic_aws_workspace_id}",
      ]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "api"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ---------- ECS ----------

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = 7
}

resource "aws_ecs_cluster" "this" {
  name = var.name
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  # Matches the amd64 GitHub-hosted runners that build the image.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = local.container_name
      image     = local.image
      essential = true

      portMappings = [{
        containerPort = var.container_port
        protocol      = "tcp"
      }]

      # app.db.database_url() builds the connection URL from the DB_* parts.
      environment = concat(
        [
          { name = "DB_HOST", value = var.db_host },
          { name = "DB_PORT", value = tostring(var.db_port) },
          { name = "DB_NAME", value = var.db_name },
          { name = "AWS_REGION", value = var.region },
          { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
          { name = "OTEL_SERVICE_NAME", value = var.name },
        ],
        local.llm_enabled ? [
          { name = "LLM_PROVIDER", value = "aws" },
          { name = "ANTHROPIC_AWS_WORKSPACE_ID", value = var.anthropic_aws_workspace_id },
        ] : [],
      )
      secrets = [
        { name = "DB_USER", valueFrom = "${var.db_secret_arn}:username::" },
        { name = "DB_PASSWORD", valueFrom = "${var.db_secret_arn}:password::" },
      ]

      dependsOn = [{ containerName = "otel-collector", condition = "START" }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = var.region
          awslogs-stream-prefix = local.container_name
        }
      }
    },
    {
      # AWS Distro for OpenTelemetry: OTLP in on :4318, X-Ray out.
      name      = "otel-collector"
      image     = "public.ecr.aws/aws-observability/aws-otel-collector:${var.adot_version}"
      essential = false # tracing must never take the API down
      command   = ["--config=/etc/ecs/ecs-xray.yaml"]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "otel"
        }
      }
    },
  ])
}

resource "aws_ecs_service" "this" {
  name            = var.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  launch_type     = "FARGATE"
  desired_count   = var.image_tag == "" ? 0 : 1

  # scripts/start.sh runs `alembic upgrade head` on every task start; never
  # running two tasks at once during a deploy keeps migrations single-writer.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  health_check_grace_period_seconds  = 60
  wait_for_steady_state              = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = local.container_name
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront, aws_iam_role_policy.execution_db_secret]
}
