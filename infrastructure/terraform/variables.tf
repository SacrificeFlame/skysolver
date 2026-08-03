variable "aws_region" {
  type    = string
  default = "ap-south-1"
}
variable "dr_region" {
  type    = string
  default = "ap-south-2"
}
variable "enable_disaster_recovery" {
  type    = bool
  default = false
}
variable "environment" {
  type = string
  validation {
    condition     = contains(["development", "integration", "airline-sandbox", "shadow-production", "controlled-production", "disaster-recovery"], var.environment)
    error_message = "Use one of the gated SkySolver environment names."
  }
}
variable "name" {
  type    = string
  default = "skysolver"
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "kubernetes_version" {
  type    = string
  default = "1.31"
}
variable "database_name" {
  type    = string
  default = "skysolver"
}
variable "database_master_username" {
  type      = string
  default   = "skysolver_admin"
  sensitive = true
}
variable "alarm_topic_arn" {
  type    = string
  default = ""
}
variable "public_edge_enabled" {
  type    = bool
  default = false
}
variable "hosted_zone_id" {
  type    = string
  default = ""
}
variable "dashboard_hostname" {
  type    = string
  default = ""
}
variable "acm_certificate_arn" {
  type    = string
  default = ""
}
variable "cognito_domain_prefix" {
  type    = string
  default = ""
}
variable "saml_metadata_url" {
  type    = string
  default = ""
}
variable "saml_idp_name" {
  type    = string
  default = "airline-workforce"
}
variable "carrier_writes_enabled" {
  type        = bool
  default     = false
  description = "Safety interlock. CI policy must reject true until controlled-production approval exists."
  validation {
    condition     = var.carrier_writes_enabled == false
    error_message = "This baseline cannot enable carrier writes. Use an airline-approved controlled-production overlay."
  }
}
