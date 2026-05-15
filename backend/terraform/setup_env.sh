#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# BusTrack — Terraform Environment Setup & Deployment Script
# ──────────────────────────────────────────────────────────────────────────────
#
# Reads your backend/.env file and generates terraform.tfvars automatically.
# Then runs terraform plan / apply / destroy as requested.
#
# Usage:
#   cd terraform
#   chmod +x setup_env.sh
#   ./setup_env.sh              # interactive mode
#   ./setup_env.sh --apply      # skip confirmation, apply directly
#   ./setup_env.sh --plan       # only plan
#   ./setup_env.sh --destroy    # destroy infrastructure
#   ./setup_env.sh --output     # show current outputs
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
TFVARS_FILE="$SCRIPT_DIR/terraform.tfvars"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[⚠]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; }
header()  { echo -e "\n${CYAN}═══ $* ═══${NC}\n"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║         BusTrack — Terraform Deployment Tool          ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Check prerequisites ──────────────────────────────────────────────────────
check_prereqs() {
    local missing=0

    if ! command -v terraform &>/dev/null; then
        error "terraform not found. Install from https://developer.hashicorp.com/terraform/install"
        missing=1
    fi

    if ! command -v az &>/dev/null; then
        error "azure-cli not found. Install from https://learn.microsoft.com/en-us/cli/azure/install-azure-cli"
        missing=1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        error ".env file not found at $ENV_FILE"
        info "Copy .env.example to .env and fill in your values first."
        missing=1
    fi

    if [ "$missing" -eq 1 ]; then
        exit 1
    fi

    success "All prerequisites found"
}

# ── Parse .env file ──────────────────────────────────────────────────────────
parse_env() {
    local key="$1"
    local default="${2:-}"
    local value

    value=$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2- | sed 's/^"//;s/"$//' || true)

    if [ -z "$value" ]; then
        echo "$default"
    else
        echo "$value"
    fi
}

# ── Extract Redis host from URL ───────────────────────────────────────────────
extract_redis_host() {
    local url="$1"
    # rediss://default:TOKEN@host:6379 → host
    echo "$url" | sed -E 's|rediss?://[^@]+@([^:]+):.*|\1|'
}

# ── Extract Redis token from URL ──────────────────────────────────────────────
extract_redis_token() {
    local url="$1"
    # rediss://default:TOKEN@host:6379 → TOKEN
    echo "$url" | sed -E 's|rediss?://[^@]+:([^@]+)@.*|\1|'
}

# ── Generate terraform.tfvars ────────────────────────────────────────────────
generate_tfvars() {
    header "Reading configuration from .env"

    # Read values from .env
    local DATABASE_URL REDIS_URL SECRET_KEY GOOGLE_CLIENT_ID
    local RESEND_API_KEY RESEND_FROM_EMAIL APP_BASE_URL

    DATABASE_URL=$(parse_env "DATABASE_URL")
    REDIS_URL=$(parse_env "REDIS_URL")
    SECRET_KEY=$(parse_env "SECRET_KEY")
    GOOGLE_CLIENT_ID=$(parse_env "GOOGLE_CLIENT_ID" "")
    RESEND_API_KEY=$(parse_env "RESEND_API_KEY" "")
    RESEND_FROM_EMAIL=$(parse_env "RESEND_FROM_EMAIL" "noreply@bustrack.dpdns.org")
    APP_BASE_URL=$(parse_env "APP_BASE_URL" "https://bustrack.dpdns.org")

    # Convert postgresql:// to postgresql+asyncpg:// if needed
    if [[ "$DATABASE_URL" == postgresql://* ]]; then
        DATABASE_URL="${postgresql://postgresql+asyncpg://}"
        info "Converted DATABASE_URL to asyncpg format"
    fi

    # If DATABASE_URL doesn't have asyncpg, add it
    if [[ "$DATABASE_URL" == postgres://* ]] && [[ "$DATABASE_URL" != *+asyncpg* ]]; then
        DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|postgres://|postgresql+asyncpg://|')
        info "Converted DATABASE_URL to asyncpg format"
    fi

    # Extract Redis host and token from URL
    local REDIS_HOST REDIS_TOKEN
    REDIS_HOST=$(extract_redis_host "$REDIS_URL")
    REDIS_TOKEN=$(extract_redis_token "$REDIS_URL")

    # Validate required values
    local missing=0
    if [ -z "$DATABASE_URL" ] || [ "$DATABASE_URL" = "" ]; then
        error "DATABASE_URL is empty in .env"
        missing=1
    fi
    if [ -z "$REDIS_URL" ] || [ "$REDIS_URL" = "" ]; then
        error "REDIS_URL is empty in .env"
        missing=1
    fi
    if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "" ]; then
        error "SECRET_KEY is empty in .env"
        missing=1
    fi

    if [ "$missing" -eq 1 ]; then
        error "Missing required values. Please check your .env file."
        exit 1
    fi

    # Show what we found
    info "DATABASE_URL:  ${DATABASE_URL:0:60}..."
    info "REDIS_HOST:    $REDIS_HOST"
    info "SECRET_KEY:    ${SECRET_KEY:0:16}..."
    info "RESEND_FROM:   $RESEND_FROM_EMAIL"
    info "APP_BASE_URL:  $APP_BASE_URL"
    info "GOOGLE_CLIENT: ${GOOGLE_CLIENT_ID:-not set}"

    # Generate tfvars
    cat > "$TFVARS_FILE" <<TFVARS
# ──────────────────────────────────────────────────────────────────────────────
# BusTrack — Terraform Variables (auto-generated by setup_env.sh)
# Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# ──────────────────────────────────────────────────────────────────────────────

project_name = "bustrack"
environment  = "prod"
location     = "eastus"

# B1 = basic tier (cheapest with always-on), P1v2 = production
app_service_sku = "B1"

# Docker image — pushed to ACR created by Terraform
docker_image = "bustrackacr.azurecr.io/bustrack-api:latest"

# ── Supabase ──
supabase_db_url = "$DATABASE_URL"

# ── Upstash Redis ──
upstash_redis_host  = "$REDIS_HOST"
upstash_redis_token = "$REDIS_TOKEN"

# ── Resend ──
resend_api_key    = "$RESEND_API_KEY"
resend_from_email = "$RESEND_FROM_EMAIL"

# ── Google OAuth ──
google_client_id = "$GOOGLE_CLIENT_ID"

# ── App Secrets ──
secret_key = "$SECRET_KEY"

# Frontend URL for email verification/reset links
app_base_url = "$APP_BASE_URL"

# CORS origins
cors_origins = "$APP_BASE_URL"
TFVARS

    success "Generated terraform.tfvars"
    warn "This file contains secrets — it is gitignored automatically"
}

# ── Terraform init ────────────────────────────────────────────────────────────
tf_init() {
    header "Initializing Terraform"

    if [ ! -d "$SCRIPT_DIR/.terraform" ]; then
        terraform init
    else
        info "Terraform already initialized, refreshing..."
        terraform init -upgrade
    fi

    success "Terraform initialized"
}

# ── Terraform plan ────────────────────────────────────────────────────────────
tf_plan() {
    header "Running Terraform Plan"
    terraform plan -var-file="$TFVARS_FILE"
}

# ── Terraform apply ───────────────────────────────────────────────────────────
tf_apply() {
    header "Deploying Infrastructure"

    echo -e "${YELLOW}This will create:${NC}"
    echo "  • Azure Resource Group (bustrack-prod-rg)"
    echo "  • Azure Container Registry (bustrackacr)"
    echo "  • Azure App Service Plan (B1)"
    echo "  • Azure Linux Web App (bustrack-prod-api)"
    echo "  • DNS Zone (bustrack.dpdns.org)"
    echo "  • Custom domain binding (api.bustrack.dpdns.org)"
    echo ""

    if [ "${1:-}" != "--yes" ]; then
        read -rp "Continue? [y/N] " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            info "Aborted."
            exit 0
        fi
    fi

    terraform apply -var-file="$TFVARS_FILE" -auto-approve

    header "Deployment Complete"
    echo ""
    terraform output
    echo ""
    success "API URL: $(terraform output -raw app_service_url 2>/dev/null || echo 'see above')"
    success "Custom domain: https://api.bustrack.dpdns.org"
    echo ""
    terraform output dns_config 2>/dev/null || true
    echo ""
    info "Next steps:"
    info "  1. Configure DNS CNAME at dpdns.org (see above)"
    info "  2. Push Docker image: docker push \$(terraform output -raw acr_login_server)/bustrack-api:latest"
    info "  3. Run migrations against Supabase"
    info "  4. Verify: curl https://api.bustrack.dpdns.org/health"
}

# ── Terraform destroy ─────────────────────────────────────────────────────────
tf_destroy() {
    header "Destroying Infrastructure"

    echo -e "${RED}WARNING: This will DELETE all Azure resources!${NC}"
    echo ""

    if [ "${1:-}" != "--yes" ]; then
        read -rp "Type 'destroy' to confirm: " confirm
        if [ "$confirm" != "destroy" ]; then
            info "Aborted."
            exit 0
        fi
    fi

    terraform destroy -var-file="$TFVARS_FILE" -auto-approve
    success "Infrastructure destroyed"
}

# ── Show outputs ──────────────────────────────────────────────────────────────
tf_output() {
    header "Current Infrastructure"
    terraform output 2>/dev/null || info "No infrastructure deployed yet. Run with --apply first."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    check_prereqs

    case "${1:-}" in
        --apply)
            generate_tfvars
            tf_init
            tf_plan
            tf_apply --yes
            ;;
        --plan)
            generate_tfvars
            tf_init
            tf_plan
            ;;
        --destroy)
            if [ -f "$TFVARS_FILE" ]; then
                tf_init
                tf_destroy
            else
                error "terraform.tfvars not found. Run without --destroy first."
                exit 1
            fi
            ;;
        --output)
            tf_output
            ;;
        --help|-h)
            echo "Usage: $0 [OPTION]"
            echo ""
            echo "Options:"
            echo "  (none)     Interactive mode — generate tfvars, plan, and prompt to apply"
            echo "  --apply    Generate tfvars, plan, and apply automatically"
            echo "  --plan     Generate tfvars and plan only (no deployment)"
            echo "  --destroy  Destroy all infrastructure (requires confirmation)"
            echo "  --output   Show current Terraform outputs"
            echo "  --help     Show this help"
            ;;
        *)
            # Interactive mode
            generate_tfvars
            tf_init
            tf_plan

            echo ""
            read -rp "Apply this plan? [y/N] " confirm
            if [[ "$confirm" =~ ^[Yy]$ ]]; then
                tf_apply --yes
            else
                info "Plan saved. Run '$0 --apply' when ready to deploy."
            fi
            ;;
    esac
}

main "$@"
