terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "bustrack"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "eastus"
}

variable "app_service_sku" {
  description = "App Service Plan SKU"
  type        = string
  default     = "B1"
}

variable "supabase_db_url" {
  type      = string
  sensitive = true
}

variable "upstash_redis_host" {
  type = string
}

variable "upstash_redis_token" {
  type      = string
  sensitive = true
}

variable "resend_api_key" {
  type      = string
  sensitive = true
}

variable "resend_from_email" {
  type    = string
  default = "noreply@bustrack.dpdns.org"
}

variable "google_client_id" {
  type    = string
  default = ""
}

variable "secret_key" {
  type      = string
  sensitive = true
}

variable "app_base_url" {
  type    = string
  default = "https://bustrack.dpdns.org"
}

variable "cors_origins" {
  type    = string
  default = "*"
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "${local.name_prefix}-rg"
  location = var.location
  tags     = local.common_tags
}

resource "azurerm_container_registry" "acr" {
  name                = "${var.project_name}acr"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Basic"
  admin_enabled       = true
  tags                = local.common_tags
}

resource "azurerm_service_plan" "main" {
  name                = "${local.name_prefix}-plan"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = var.app_service_sku
  tags                = local.common_tags
}

resource "azurerm_linux_web_app" "api" {
  name                = "${local.name_prefix}-api"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  service_plan_id     = azurerm_service_plan.main.id
  https_only          = true

  site_config {
    always_on          = var.app_service_sku != "F1"
    ftps_state         = "Disabled"
    http2_enabled      = true
    websockets_enabled = true

    application_stack {
      docker_image_name        = "bustrack-api:latest"
      docker_registry_url      = "https://${azurerm_container_registry.acr.login_server}"
      docker_registry_username = azurerm_container_registry.acr.admin_username
      docker_registry_password = azurerm_container_registry.acr.admin_password
    }

    minimum_tls_version = "1.2"
  }

  app_settings = {
    DATABASE_URL                        = var.supabase_db_url
    REDIS_URL                           = "rediss://default:${var.upstash_redis_token}@${var.upstash_redis_host}:6379"
    SECRET_KEY                          = var.secret_key
    APP_BASE_URL                        = var.app_base_url
    CORS_ORIGINS                        = var.cors_origins
    FIREWALL_ENABLED                    = "true"
    GOOGLE_CLIENT_ID                    = var.google_client_id
    RESEND_API_KEY                      = var.resend_api_key
    RESEND_FROM_EMAIL                   = var.resend_from_email
    TRUSTED_PROXY_IPS                   = "*"
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    WEBSITES_PORT                       = "8000"
  }

  tags = local.common_tags
}

resource "azurerm_app_service_custom_hostname_binding" "api" {
  hostname            = "api.bustrack.dpdns.org"
  app_service_name    = azurerm_linux_web_app.api.name
  resource_group_name = azurerm_resource_group.main.name

  lifecycle {
    ignore_changes = [ssl_state, thumbprint]
  }
}

output "app_service_url" {
  value = "https://${azurerm_linux_web_app.api.default_hostname}"
}

output "custom_domain_url" {
  value = "https://api.bustrack.dpdns.org"
}

output "app_service_name" {
  value = azurerm_linux_web_app.api.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "acr_admin_username" {
  value     = azurerm_container_registry.acr.admin_username
  sensitive = true
}

output "acr_admin_password" {
  value     = azurerm_container_registry.acr.admin_password
  sensitive = true
}

output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "dns_config" {
  value = "CNAME api.bustrack.dpdns.org → ${azurerm_linux_web_app.api.default_hostname}"
}