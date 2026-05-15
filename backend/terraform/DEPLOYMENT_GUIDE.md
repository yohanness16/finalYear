# BusTrack — Complete Azure Deployment Guide

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Azure Cloud                                   │
│  ┌─────────────────────┐    ┌──────────────────────────────────┐    │
│  │  Container Registry  │───▶│  App Service (Linux, Docker)     │    │
│  │  (ACR)               │    │  api.bustrack.dpdns.org          │    │
│  └─────────────────────┘    │  ┌────────────────────────────┐  │    │
│                              │  │  FastAPI + OpenCV          │  │    │
│                              │  │  Port 8000                  │  │    │
│                              │  └──────────┬─────────────────┘  │    │
│                              └─────────────┼────────────────────┘    │
└────────────────────────────────────────────┼─────────────────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        ▼
           ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
           │   Supabase   │        │   Upstash    │        │   Resend     │
           │  PostgreSQL  │        │    Redis     │        │  (bustrack   │
           │              │        │              │        │  .dpdns.org) │
           └──────────────┘        └──────────────┘        └──────────────┘
```

## Domain Configuration

| Service | Domain |
|---------|--------|
| Frontend | `bustrack.dpdns.org` |
| Backend API | `api.bustrack.dpdns.org` |
| Email (Resend) | `noreply@bustrack.dpdns.org` |

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed
- [Terraform](https://developer.hashicorp.com/terraform/install) installed
- [Docker](https://docs.docker.com/get-docker/) installed
- A GitHub account with this repo pushed

---

## Step 1: Supabase Setup

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a region close to your Azure deployment
3. Wait ~2 minutes for provisioning
4. Go to **Settings → Database → Connection string → URI**
5. Copy the string and convert it:
   ```
   # Original:
   postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres
   
   # Change to (replace postgresql:// with postgresql+asyncpg://):
   postgresql+asyncpg://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres
   ```
6. Save this for later

### Run migrations on Supabase

```bash
cd backend

# Temporarily set DATABASE_URL to Supabase
export DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres"

# Run all migrations
alembic upgrade head

# Verify tables were created
# Check Supabase Dashboard → Table Editor
```

---

## Step 2: Upstash Redis Setup

1. Go to [upstash.com](https://upstash.com) → Sign up / Log in
2. Click **Create Database**
3. Name: `bustrack-redis`
4. Region: pick the same region as your Azure App Service
5. Click **Create**
6. Go to **Details** tab
7. Copy:
   - **REST URL** → `https://xxx-xxx-xxx.upstash.io`
   - **REST Token** → long string starting with `A...`
8. Save both for later

---

## Step 3: Resend Setup

1. Go to [resend.com](https://resend.com) → Sign up
2. Go to **API Keys** → **Create API Key**
3. Name: `bustrack-production`
4. Copy the key (starts with `re_`)
5. Save for later

### Verify Domain in Resend (Required for production email)

1. In Resend Dashboard → **Domains** → **Add Domain**
2. Enter: `bustrack.dpdns.org`
3. Resend will give you DNS records to add (TXT for SPF, DKIM, DMARC)
4. Go to your **dpdns.org** control panel and add these records:
   - **TXT** record for domain verification
   - **TXT** record for SPF (`v=spf1 include:spf.resend.com ~all`)
   - **CNAME** records for DKIM (Resend provides 3 CNAME records)
   - **TXT** record for DMARC (`v=DMARC1; p=none; rua=mailto:dmarc@bustrack.dpdns.org`)
5. Click **Verify** in Resend dashboard
6. Wait a few minutes for DNS propagation

> **Note**: Without domain verification, emails will be sent from `resend.dev` which many email providers mark as spam. Verifying `bustrack.dpdns.org` ensures emails come from `noreply@bustrack.dpdns.org`.

---

## Step 4: Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project (or create one)
3. Go to **APIs & Services → Credentials**
4. Click **Create Credentials → OAuth Client ID**
5. If prompted, configure the OAuth consent screen first:
   - User Type: **External**
   - App name: `BusTrack`
   - Add your email as support + developer
   - Add scopes: `email`, `profile`, `openid`
   - Add test users (your email) for testing
6. Application type: **Web application**
7. Name: `BusTrack Web`
8. Authorized JavaScript origins:
   ```
   https://your-frontend-domain.com
   http://localhost:3000
   ```
9. Click **Create**
10. Copy the **Client ID** (ends with `.apps.googleusercontent.com`)

---

## Step 5: Deploy Infrastructure with Terraform

```bash
cd backend/terraform

# Initialize Terraform (downloads Azure provider)
terraform init

# Copy example variables
cp variables.tfvars.example terraform.tfvars

# Edit with your real values
nano terraform.tfvars    # or use any editor

# Preview what will be created
terraform plan

# Deploy! (~3-5 minutes)
terraform apply
```

After apply, Terraform will output:
```
app_service_url     = "https://bustrack-prod-api.azurewebsites.net"
acr_login_server    = "bustrackacr.azurecr.io"
acr_admin_username  = "bustrack"
acr_admin_password  = "..."
```

**Save these values!**

---

## Step 6: Push Docker Image to ACR

```bash
cd backend

# Login to Azure
az login

# Login to ACR
az acr login --name bustrackacr

# Build the Docker image
docker build -t bustrackacr.azurecr.io/bustrack-api:latest .

# Push to ACR
docker push bustrackacr.azurecr.io/bustrack-api:latest
```

---

## Step 7: Configure App Service Environment

The Terraform config sets environment variables automatically. Verify them:

```bash
# Check current settings
az webapp config appsettings list \
  --name bustrack-prod-api \
  --resource-group bustrack-prod-rg \
  --output table
```

If any are missing, set them manually:

```bash
az webapp config appsettings set \
  --name bustrack-prod-api \
  --resource-group bustrack-prod-rg \
  --settings \
    DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres" \
    REDIS_URL="redis://default:TOKEN@xxx.upstash.io" \
    SECRET_KEY="your-jwt-secret" \
    GOOGLE_CLIENT_ID="xxx.apps.googleusercontent.com" \
    RESEND_API_KEY="re_xxxxx" \
    RESEND_FROM_EMAIL="noreply@bustrack.et" \
    APP_BASE_URL="https://bustrack.et" \
    CORS_ORIGINS="https://bustrack.et" \
    FIREWALL_ENABLED="true" \
    TRUSTED_PROXY_IPS="*" \
    WEBSITES_PORT="8000"
```

---

## Step 8: Configure DNS (dpdns.org)

After Terraform creates the App Service, you need to point your domain to it:

```bash
# Get the Azure default hostname
terraform output app_service_url
# Example output: https://bustrack-prod-api.azurewebsites.net
```

### At dpdns.org control panel:

1. Log in to your dpdns.org account
2. Find `bustrack.dpdns.org` zone
3. Add a **CNAME** record:
   ```
   Name:  api
   Value: bustrack-prod-api.azurewebsites.net
   TTL:   300
   ```
4. Save and wait ~5 minutes for DNS propagation

### Verify DNS:

```bash
# Check CNAME resolution
nslookup api.bustrack.dpdns.org

# Should resolve to the Azure hostname
```

## Step 9: Verify Deployment

```bash
# Health check (Azure default hostname)
curl https://bustrack-prod-api.azurewebsites.net/health

# Health check (custom domain — after DNS propagates)
curl https://api.bustrack.dpdns.org/health

# Expected: {"status":"healthy"} or similar

# Test registration
curl -X POST https://bustrack-prod-api.azurewebsites.net/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","email":"test@example.com","password":"Test@1234"}'

# Test login
curl -X POST https://bustrack-prod-api.azurewebsites.net/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"Test@1234"}'
```

---

## Step 9: Set Up CI/CD (GitHub Actions)

### Create Azure Service Principal

```bash
# Create service principal for GitHub Actions
az ad sp create-for-rbac \
  --name "bustrack-github-actions" \
  --role contributor \
  --scopes /subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/bustrack-prod-rg \
  --sdk-auth
```

Copy the entire JSON output.

### Add GitHub Secrets

Go to your GitHub repo → **Settings → Secrets and variables → Actions** → **New repository secret**

Add these secrets:

| Secret Name | Value |
|---|---|
| `AZURE_CREDENTIALS` | The JSON from `az ad sp create-for-rbac` |
| `ACR_USERNAME` | From Terraform output |
| `ACR_PASSWORD` | From Terraform output |
| `DATABASE_URL` | Supabase connection string |
| `REDIS_URL` | Upstash Redis URL |
| `SECRET_KEY` | JWT secret key |
| `GOOGLE_CLIENT_ID` | Google OAuth Client ID |
| `RESEND_API_KEY` | Resend API key |
| `APP_BASE_URL` | Your frontend URL |
| `CORS_ORIGINS` | Your frontend domains |

### Test CI/CD

```bash
# Push to main — this triggers the CD workflow
git add .
git commit -m "trigger deployment"
git push origin main
```

Go to GitHub → **Actions** tab → watch the CD workflow run.

---

## Step 10: Custom Domain & SSL (Optional)

### Add Custom Domain

```bash
# Add custom domain to App Service
az webapp config hostname add \
  --webapp-name bustrack-prod-api \
  --resource-group bustrack-prod-rg \
  --hostname api.bustrack.et

# Get the verification TXT record
az webapp config hostname get-external-ip \
  --webapp-name bustrack-prod-api \
  --resource-group bustrack-prod-rg
```

### Add SSL Certificate

```bash
# Create managed certificate
az webapp config ssl create \
  --resource-group bustrack-prod-rg \
  --name bustrack-prod-api \
  --hostname api.bustrack.et

# Bind certificate
az webapp config ssl bind \
  --resource-group bustrack-prod-rg \
  --name bustrack-prod-api \
  --hostname api.bustrack.et \
  --ssl-type SniEnabled
```

---

## Free Tier Limits & Costs

| Service | Free Tier | Your Usage |
|---------|-----------|------------|
| **Azure App Service (B1)** | 60 CPU min/day | ✅ Enough for demo |
| **Azure Container Registry (Basic)** | 10 GB storage | ✅ ~200 MB image |
| **Supabase** | 500 MB DB, 2 GB bandwidth/month | ✅ Enough for project |
| **Upstash** | 10K commands/day | ✅ Enough for project |
| **Resend** | 100 emails/day, 3K/month | ✅ Enough for project |
| **Google OAuth** | Unlimited | ✅ Free |

**Total cost for school project: $0/month**

---

## Troubleshooting

### App won't start
```bash
# Check logs
az webapp log tail --name bustrack-prod-api --resource-group bustrack-prod-rg

# Check container logs
az webapp log download --name bustrack-prod-api --resource-group bustrack-prod-rg
```

### Database connection errors
```bash
# Verify Supabase allows Azure IPs
# Supabase Dashboard → Settings → Network → Add Azure outbound IPs
# Or allow all IPs (less secure, fine for project):
# Supabase Dashboard → Settings → Network → Allow all
```

### Redis connection errors
```bash
# Verify Upstash allows connections from anywhere (default)
# Upstash Console → Your DB → Access Control → Allow all
```

### Docker image not updating
```bash
# Force restart
az webapp restart --name bustrack-prod-api --resource-group bustrack-prod-rg

# Or push a new tag and update the App Service
docker build -t bustrackacr.azurecr.io/bustrack-api:$(git rev-parse --short HEAD) .
docker push bustrackacr.azurecr.io/bustrack-api:$(git rev-parse --short HEAD)
```

### View all environment variables
```bash
az webapp config appsettings list \
  --name bustrack-prod-api \
  --resource-group bustrack-prod-rg \
  --output table
```
