# BusTrack — Deployment Guide

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Frontend   │────▶│  Azure App Service│────▶│  Supabase       │
│  (Your App)  │     │  (FastAPI Docker) │     │  (PostgreSQL)   │
└─────────────┘     └──────────────────┘     └─────────────────┘
                           │    ▲
                           │    │
                           ▼    │
                    ┌──────────────────┐     ┌─────────────────┐
                    │  Upstash Redis   │     │  Resend         │
                    │  (Live state +   │     │  (Email)        │
                    │   caching)       │     │                 │
                    └──────────────────┘     └─────────────────┘
```

## Step 1: Supabase Setup

1. Go to [supabase.com](https://supabase.com) → New Project
2. Wait for project to provision (~2 min)
3. Go to **Settings → Database → Connection string**
4. Copy the URI connection string
5. Replace `postgresql://` with `postgresql+asyncpg://`
6. Save this for `supabase_db_url`

### Run migrations on Supabase

```bash
# Set the DATABASE_URL to your Supabase connection string
export DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres"

# Run Alembic migrations
alembic upgrade head
```

## Step 2: Upstash Redis Setup

1. Go to [upstash.com](https://upstash.com) → Create Database
2. Choose the closest region to your Azure App Service
3. Go to **Details** tab → copy the **REST URL** and **REST Token**
4. Save these for `upstash_redis_url` and `upstash_redis_token`

## Step 3: Resend Setup

1. Go to [resend.com](https://resend.com) → Sign up
2. Go to **API Keys** → Create API Key
3. Save the key for `resend_api_key`
4. (Optional) Verify your domain for production emails

## Step 4: Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Go to **APIs & Services → Credentials**
4. Click **Create Credentials → OAuth Client ID**
5. Application type: **Web application**
6. Add authorized JavaScript origins:
   - `https://your-frontend-domain.com`
   - `http://localhost:3000` (for development)
7. Copy the Client ID for `google_client_id`

## Step 5: Docker Image

### Build and push to Docker Hub

```bash
cd backend

# Build
docker build -t yourdockerhub/bustrack:latest .

# Login
docker login

# Push
docker push yourdockerhub/bustrack:latest
```

## Step 6: Deploy with Terraform

```bash
cd terraform

# Initialize Terraform
terraform init

# Copy and edit variables
cp variables.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your real values

# Preview changes
terraform plan

# Deploy
terraform apply
```

## Step 7: Verify Deployment

```bash
# Check health
curl https://bustrack-prod-api.azurewebsites.net/health

# Test registration
curl -X POST https://bustrack-prod-api.azurewebsites.net/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","email":"test@test.com","password":"Test@1234"}'
```

## Free Tier Limits

| Service | Free Tier |
|---------|-----------|
| Azure App Service (B1) | 60 CPU minutes/day |
| Supabase | 500 MB DB, 2 GB bandwidth/month |
| Upstash | 10K commands/day, 256 MB |
| Resend | 100 emails/day, 3000/month |
| Google OAuth | Unlimited |

## Cost Estimate (Production)

For a production deployment with more resources:
- Azure App Service P1v2: ~$73/month
- Supabase Pro: $25/month (if you outgrow free)
- Upstash Pay-as-you-go: ~$5-10/month
- Resend Free tier: $0 (up to 3000 emails/month)

**Total for school project: $0/month** (all free tiers)
