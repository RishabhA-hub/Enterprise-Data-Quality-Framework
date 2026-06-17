# =====================================================================
# Per-environment tfvars (example: prd)
# Apply: terraform apply -var-file=envs/prd.tfvars
# =====================================================================
environment       = "prd"
vpc_id            = "vpc-0abc123def456"
subnet_ids        = ["subnet-aaa","subnet-bbb","subnet-ccc"]
db_instance_class = "db.r6g.xlarge"
db_allocated_gb   = 500
retention_years   = 7
