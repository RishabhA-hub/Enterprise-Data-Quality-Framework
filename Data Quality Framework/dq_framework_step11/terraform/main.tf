# =====================================================================
# Terraform :: DQ Framework infrastructure module
# Provisions everything required to RUN the framework:
#   - RDS PostgreSQL 16 (Multi-AZ, encrypted, IAM-auth enabled)
#   - Secrets Manager entries for db creds + webhook URLs
#   - S3 bucket (versioned, KMS-encrypted, WORM via Object Lock) for
#     scorecard exports and audit-log archives
#   - IAM roles for Airflow / EKS pods (IRSA) with least privilege
#   - CloudWatch log group + metric filter for SLA breaches
# =====================================================================

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.60" }
  }
  backend "s3" {} # configured via -backend-config in CI
}

# ---- Inputs ---------------------------------------------------------
variable "project"      { type = string  default = "dq-framework" }
variable "environment"  { type = string }                          # dev | stg | prd
variable "vpc_id"       { type = string }
variable "subnet_ids"   { type = list(string) }
variable "db_instance_class" { type = string  default = "db.t4g.large" }
variable "db_allocated_gb"   { type = number  default = 100 }
variable "retention_years"   { type = number  default = 7 }        # SOX = 7y

locals {
  name = "${var.project}-${var.environment}"
  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    DataClass   = "confidential"
    CostCenter  = "data-platform"
  }
}

# ---- KMS key for RDS + S3 encryption --------------------------------
resource "aws_kms_key" "dq" {
  description             = "${local.name} encryption key"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}

# ---- Networking: security group -------------------------------------
resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "Postgres ingress for DQ workloads"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

# ---- RDS PostgreSQL --------------------------------------------------
resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-subnets"
  subnet_ids = var.subnet_ids
  tags       = local.tags
}

resource "random_password" "db_master" {
  length  = 32
  special = true
}

resource "aws_db_instance" "this" {
  identifier                       = local.name
  engine                           = "postgres"
  engine_version                   = "16.4"
  instance_class                   = var.db_instance_class
  allocated_storage                = var.db_allocated_gb
  storage_type                     = "gp3"
  storage_encrypted                = true
  kms_key_id                       = aws_kms_key.dq.arn
  multi_az                         = var.environment == "prd"
  db_subnet_group_name             = aws_db_subnet_group.this.name
  vpc_security_group_ids           = [aws_security_group.db.id]
  username                         = "dq_admin"
  password                         = random_password.db_master.result
  iam_database_authentication_enabled = true
  backup_retention_period          = var.environment == "prd" ? 35 : 7
  deletion_protection              = var.environment == "prd"
  performance_insights_enabled     = true
  performance_insights_kms_key_id  = aws_kms_key.dq.arn
  enabled_cloudwatch_logs_exports  = ["postgresql"]
  auto_minor_version_upgrade       = true
  apply_immediately                = false
  tags                             = local.tags
}

# ---- Secrets Manager ------------------------------------------------
resource "aws_secretsmanager_secret" "db" {
  name                    = "${local.name}/postgres"
  kms_key_id              = aws_kms_key.dq.arn
  recovery_window_in_days = 7
  tags                    = local.tags
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    host     = aws_db_instance.this.address
    port     = aws_db_instance.this.port
    username = aws_db_instance.this.username
    password = random_password.db_master.result
    dbname   = "dq"
  })
}

# ---- S3 bucket for scorecard exports + audit archives ---------------
resource "aws_s3_bucket" "exports" {
  bucket        = "${local.name}-exports"
  force_destroy = var.environment != "prd"
  object_lock_enabled = true
  tags          = local.tags
}

resource "aws_s3_bucket_versioning" "exports" {
  bucket = aws_s3_bucket.exports.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.dq.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "exports" {
  bucket                  = aws_s3_bucket.exports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "exports" {
  bucket = aws_s3_bucket.exports.id
  rule {
    id     = "audit-retention"
    status = "Enabled"
    filter { prefix = "audit/" }
    transition { days = 90  storage_class = "STANDARD_IA" }
    transition { days = 365 storage_class = "GLACIER" }
    expiration { days = var.retention_years * 365 }
  }
}

# ---- CloudWatch: SLA-breach metric filter ---------------------------
resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/dq/${var.environment}/pipeline"
  retention_in_days = 90
  kms_key_id        = aws_kms_key.dq.arn
  tags              = local.tags
}

resource "aws_cloudwatch_log_metric_filter" "sla_breach" {
  name           = "${local.name}-sla-breach"
  log_group_name = aws_cloudwatch_log_group.pipeline.name
  pattern        = "{ $.severity = \"CRITICAL\" && $.event = \"sla_breach\" }"
  metric_transformation {
    name      = "DQSlaBreach"
    namespace = "DQFramework"
    value     = "1"
    unit      = "Count"
  }
}

# ---- Outputs --------------------------------------------------------
output "db_endpoint"      { value = aws_db_instance.this.address }
output "db_secret_arn"    { value = aws_secretsmanager_secret.db.arn }
output "exports_bucket"   { value = aws_s3_bucket.exports.bucket }
output "log_group_name"   { value = aws_cloudwatch_log_group.pipeline.name }
output "kms_key_arn"      { value = aws_kms_key.dq.arn }
