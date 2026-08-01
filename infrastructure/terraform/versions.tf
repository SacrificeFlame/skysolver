terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Product     = "SkySolver"
      Environment = var.environment
      ManagedBy   = "Terraform"
      OperationalAuthority = "disabled"
    }
  }
}

provider "aws" {
  alias  = "dr"
  region = var.dr_region
  default_tags {
    tags = {
      Product              = "SkySolver"
      Environment          = var.environment
      ManagedBy            = "Terraform"
      OperationalAuthority = "disabled"
      RecoveryRegion       = "true"
    }
  }
}
