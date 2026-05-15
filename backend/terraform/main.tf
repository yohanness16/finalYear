# ──────────────────────────────────────────────────────────────────────────────
# BusTrack — Azure Deployment with Supabase PostgreSQL + Upstash Redis
# ──────────────────────────────────────────────────────────────────────────────
#
# Architecture:
#   Azure App Service (Docker) → Supabase (PostgreSQL) + Upstash (Redis)
#
# Prerequisites:
#   1. Supabase project → Settings → Database → Connection string
#   2. Upstash Redis → REST URL + Token
#   3. Resend API key → resend.com/api-keys
#   4. Google OAuth Client ID → console.cloud.google.com
#   5. Azure CLI login → az login
#
# Usage:
#   cd terraform
#   terraform init
#   cp variables.tfvars.example terraform.tfvars
#   # Edit terraform.tfvars with your values
#   terraform plan
#   terraform apply
# ──────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.5"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }

  # Optional: store state in Azure Storage (recommended for team use)
  # backend "azurerm" {
  #   resource_group_name  = "bustrack-terraform-state"
  #   storage_account_name = "bustracktfstate"
  #   container_name       = "tfstate"
  #   key                  = "prod.terraform.tfstate"
  # }
}

provider "azurerm" {
  features {}
}

# ── Variables ─────────────────────────────────────────────────────────────────

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
  description = "App Service Plan SKU (B1=dev, P1v2=production)"
  type        = string
  default     = "B1"
}

variable "docker_image" {
  description = "Docker image with tag (e.g., bustrack.azurecr.io/bustrack-api:latest)"
  type        = string
}

variable "supabase_db_url" {
  description = "Supabase PostgreSQL connection string (postgresql+asyncpg://...)"
  type        = string
  sensitive   = true
}

variable "upstash_redis_url" {
  description = "Upstash Redis REST URL (https://...upstash.io)"
  type        = string
  sensitive   = true
}

variable "upstash_redis_token" {
  description = "Upstash Redis REST token"
  type        = string
  sensitive   = true
}

variable "resend_api_key" {
  description = "Resend API key for transactional emails"
  type        = string
  sensitive   = true
}

variable "resend_from_email" {
  description = "From address for Resend emails"
  type        = string
  default     = "noreply@bustrack.et"
}

variable "google_client_id" {
  description = "Google OAuth Client ID"
  type        = string
  default     = ""
}

variable "secret_key" {
  description = "JWT secret key (generate with: openssl rand -hex 32)"
  type        = string
  sensitive   = true
}

variable "app_base_url" {
  description = "Frontend app base URL (for email verification/reset links)"
  type        = string
  default     = "https://bustrack.et"
}

variable "cors_origins" {
  description = "Allowed CORS origins (comma-separated)"
  type        = string
  default     = "*"
}

# ── Locals ────────────────────────────────────────────────────────────────────

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ── Resource Group ───────────────────────────────────────────────────────────

resource "azurerm_resource_group" "main" {
  name     = "${local.name_prefix}-rg"
  location = var.location
  tags     = local.common_tags
}

# ── Azure Container Registry ─────────────────────────────────────────────────

resource "azurerm_container_registry" "acr" {
  name                = "${var.project_name}acr"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Basic"
  admin_enabled       = true
  tags                = local.common_tags
}

# ── App Service Plan ─────────────────────────────────────────────────────────

resource "azurerm_service_plan" "main" {
  name                = "${local.name_prefix}-plan"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = var.app_service_sku
  tags                = local.common_tags
}

# ── Linux Web App (FastAPI) ─────────────────────────────────────────────────

resource "azurerm_linux_web_app" "api" {
  name                = "${local.name_prefix}-api"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  service_plan_id     = azurerm_service_plan.main.id
  https_only          = true

  site_config {
    always_on     = var.app_service_sku != "F1"
    ftps_state    = "Disabled"
    http2_enabled = true
    websockets_enabled = true

    application_stack {
      docker_image     = var.docker_image
      docker_registry_url      = "https://${azurerm_container_registry.acr.login_server}"
      docker_registry_username = azurerm_container_registry.acr.admin_username
      docker_registry_password = azurerm_container_registry.acr.admin_password
    }

    minimum_tls_version = "1.2"
  }

  # Application settings (environment variables)
  app_settings = {
    # ── Database (Supabase) ──
    DATABASE_URL = var.supabase_db_url

    # ── Redis (Upstash) ──
    REDIS_URL = "redis://default:${var.upstash_redis_token}@${replace(replace(var.upstash_redis_url, "https://", ""), "http://", "")}"

    # ── App ──
    SECRET_KEY       = var.secret_key
    APP_BASE_URL     = var.app_base_url
    CORS_ORIGINS     = var.cors_origins
    FIREWALL_ENABLED = "true"

    # ── Google OAuth ──
    GOOGLE_CLIENT_ID = var.google_client_id

    # ── Email (Resend) ──
    RESEND_API_KEY    = var.resend_api_key
    RESEND_FROM_EMAIL = var.resend_from_email

    # ── Security ──
    TRUSTED_PROXY_IPS = "*"

    # ── Azure-specific ──
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    WEBSITES_PORT                       = "8000"
  }

  tags = local.common_tags
}

# ── Outputs ──────────────────────────────────────────────────────────────────

output "app_service_url" {
  description = "URL of the deployed API"
  value       = "https://${azurerm_linux_web_app.api.default_hostname}"
}

output "app_service_name" {
  description = "Name of the App Service"
  value       = azurerm_linux_web_app.api.name
}

output "acr_login_server" {
  description = "ACR login server (for docker push)"
  value       = azurerm_container_registry.acr.login_server
}

output "acr_admin_username" {
  description = "ACR admin username"
  value       = azurerm_container_registry.acr.admin_username
  sensitive   = true
}

output "acr_admin_password" {
  description = "ACR admin password"
  value       = azurerm_container_registry.acr.admin_password
  sensitive   = true
}

output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.main.name
}
