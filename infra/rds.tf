# Aurora PostgreSQL in the same VPC as DeployGuard EC2 — cheapest single-instance setup.
# Smallest Aurora class: db.t4g.medium (Aurora does not offer micro/small burstable sizes).

resource "random_password" "db_master" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "incidents" {
  name       = "${local.name_prefix}-aurora-subnets"
  subnet_ids = aws_subnet.public[*].id

  tags = {
    Name = "${local.name_prefix}-aurora-subnets"
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "Aurora PostgreSQL — DeployGuard EC2 only"
  vpc_id      = local.vpc_id

  ingress {
    description     = "PostgreSQL from DeployGuard EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-rds-sg"
  }
}

resource "aws_rds_cluster" "incidents" {
  cluster_identifier = "${local.name_prefix}-aurora"
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = var.aurora_engine_version

  database_name   = var.db_name
  master_username = var.db_master_username
  master_password = random_password.db_master.result

  db_subnet_group_name   = aws_db_subnet_group.incidents.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  storage_encrypted = true

  backup_retention_period   = var.db_backup_retention_days
  preferred_backup_window   = "03:00-04:00"
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${local.name_prefix}-aurora-final" : null
  deletion_protection       = var.environment == "prod"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  tags = {
    Name = "${local.name_prefix}-aurora"
  }
}

resource "aws_rds_cluster_instance" "incidents" {
  identifier         = "${local.name_prefix}-aurora-1"
  cluster_identifier = aws_rds_cluster.incidents.id
  instance_class     = var.aurora_instance_class
  engine             = aws_rds_cluster.incidents.engine
  engine_version     = aws_rds_cluster.incidents.engine_version

  performance_insights_enabled = false
  monitoring_interval          = 0

  tags = {
    Name = "${local.name_prefix}-aurora-1"
  }
}

resource "aws_secretsmanager_secret" "database" {
  name        = "${local.name_prefix}/database"
  description = "DeployGuard Aurora PostgreSQL connection (host, user, password, dbname)"
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    host     = aws_rds_cluster.incidents.endpoint
    port     = tostring(aws_rds_cluster.incidents.port)
    username = var.db_master_username
    password = random_password.db_master.result
    dbname   = var.db_name
    engine   = "postgres"
  })

  depends_on = [aws_rds_cluster_instance.incidents]
}
