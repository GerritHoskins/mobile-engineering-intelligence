resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

# No inline rules: the service module adds the one ingress rule (5432 from the
# service security group), which avoids a module dependency cycle.
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Postgres, reachable only from the ECS service"
  vpc_id      = var.vpc_id
}

resource "aws_db_instance" "this" {
  identifier     = var.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.username
  # RDS generates the password and keeps it in Secrets Manager, so it never
  # appears in Terraform code, variables, state outputs or the task definition.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false

  # Dev-grade: fast, cheap, disposable.
  backup_retention_period = 0
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true
}
