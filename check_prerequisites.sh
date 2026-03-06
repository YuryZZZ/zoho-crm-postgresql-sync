#!/usr/bin/env bash
set -euo pipefail

echo "🔍 Checking Zoho Mail to GCloud Archiver prerequisites..."
echo "======================================================"

# Check Docker
echo "🐳 Checking Docker..."
if command -v docker &> /dev/null; then
    if docker ps &> /dev/null; then
        echo "✅ Docker is installed and running"
    else
        echo "❌ Docker is installed but not running"
        echo "   Please start Docker Desktop"
        exit 1
    fi
else
    echo "❌ Docker is not installed"
    echo "   Please install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    exit 1
fi

# Check gcloud
echo "☁️  Checking gcloud CLI..."
if command -v gcloud &> /dev/null; then
    echo "✅ gcloud CLI is installed"
    
    # Check authentication
    if gcloud auth list --format="value(account)" | grep -q "@"; then
        echo "✅ gcloud is authenticated"
    else
        echo "❌ gcloud is not authenticated"
        echo "   Run: gcloud auth login"
        exit 1
    fi
    
    # Check project
    PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
    if [[ -n "$PROJECT" && "$PROJECT" != "(unset)" ]]; then
        echo "✅ Project is set: $PROJECT"
    else
        echo "❌ No project set"
        echo "   Run: gcloud config set project PROJECT_ID"
        exit 1
    fi
else
    echo "❌ gcloud CLI is not installed"
    echo "   Please install Google Cloud SDK from https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check .env file
echo "📄 Checking environment file..."
if [[ -f ".env" ]]; then
    echo "✅ .env file exists"
    
    # Check for required variables
    missing_vars=()
    for var in PROJECT_ID GCS_BUCKET_NAME ZOHO_CLIENT_ID ZOHO_CLIENT_SECRET ZOHO_REFRESH_TOKEN ZOHO_ACCOUNT_ID; do
        if ! grep -q "^$var=" .env; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -eq 0 ]]; then
        echo "✅ All required environment variables are set"
    else
        echo "❌ Missing environment variables: ${missing_vars[*]}"
        echo "   Please update your .env file"
        exit 1
    fi
else
    echo "❌ .env file not found"
    echo "   Copy .env.template to .env and fill in your values"
    exit 1
fi

# Check deployment script
echo "📦 Checking deployment script..."
if [[ -f "deploy_all.sh" ]]; then
    echo "✅ deploy_all.sh exists"
    
    # Check if executable
    if [[ -x "deploy_all.sh" ]]; then
        echo "✅ deploy_all.sh is executable"
    else
        echo "⚠️  deploy_all.sh is not executable"
        echo "   Run: chmod +x deploy_all.sh"
    fi
else
    echo "❌ deploy_all.sh not found"
    exit 1
fi

# Check Dockerfile
echo "🐋 Checking Dockerfile..."
if [[ -f "Dockerfile" ]]; then
    echo "✅ Dockerfile exists"
else
    echo "❌ Dockerfile not found"
    exit 1
fi

echo ""
echo "======================================================"
echo "🎉 All prerequisites are satisfied!"
echo ""
echo "🚀 Ready to deploy with:"
echo "   ./deploy_all.sh"
echo ""
echo "📊 After deployment, access dashboard at:"
echo "   https://zoho-mail-archiver-enhanced-*.run.app"
echo "======================================================"