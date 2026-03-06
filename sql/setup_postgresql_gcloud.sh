#!/bin/bash
# PostgreSQL Setup Script for Google Cloud SQL
# Zoho CRM Digital Twin - Bidirectional Sync Database

set -e  # Exit on error

echo "========================================="
echo "ZOHO CRM DIGITAL TWIN - POSTGRESQL SETUP"
echo "Google Cloud SQL Configuration"
echo "========================================="

# Configuration
DB_NAME="zoho_crm_digital_twin"
DB_USER="zoho_sync_user"
DB_PASSWORD=$(openssl rand -base64 32)  # Generate secure password
INSTANCE_NAME="zoho-crm-postgres-instance"
REGION="europe-west1"
TIER="db-f1-micro"  # Change to db-g1-small for production

echo "🔧 Configuration:"
echo "   Database: $DB_NAME"
echo "   User: $DB_USER"
echo "   Region: $REGION"
echo "   Tier: $TIER"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ Google Cloud SDK (gcloud) is not installed."
    echo "   Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if user is authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    echo "🔐 Please authenticate with Google Cloud:"
    gcloud auth login
fi

# Set project
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "❌ No project configured. Set with: gcloud config set project PROJECT_ID"
    exit 1
fi
echo "   Project: $PROJECT_ID"

# Create Cloud SQL PostgreSQL instance
echo ""
echo "🚀 Creating Cloud SQL PostgreSQL instance..."
gcloud sql instances create $INSTANCE_NAME \
    --database-version=POSTGRES_15 \
    --cpu=1 \
    --memory=3840MB \
    --region=$REGION \
    --tier=$TIER \
    --storage-type=SSD \
    --storage-size=10GB \
    --backup-start-time=02:00 \
    --enable-point-in-time-recovery \
    --maintenance-window-day=SUN \
    --maintenance-window-hour=03 \
    --database-flags=cloudsql.enable_pg_cron=on,cloudsql.enable_pglogical=on \
    --labels=environment=production,purpose=zoho-crm-sync

echo "✅ Cloud SQL instance created: $INSTANCE_NAME"

# Set root password (if not already set)
echo ""
echo "🔐 Setting database password..."
gcloud sql users set-password postgres \
    --instance=$INSTANCE_NAME \
    --password="$DB_PASSWORD"

# Create database
echo ""
echo "📁 Creating database: $DB_NAME"
gcloud sql databases create $DB_NAME --instance=$INSTANCE_NAME

# Create application user
echo ""
echo "👤 Creating application user: $DB_USER"
gcloud sql users create $DB_USER \
    --instance=$INSTANCE_NAME \
    --password="$DB_PASSWORD"

# Get instance connection name
CONNECTION_NAME=$(gcloud sql instances describe $INSTANCE_NAME --format="value(connectionName)")
echo ""
echo "🔗 Connection name: $CONNECTION_NAME"

# Create local connection for schema setup
echo ""
echo "📦 Setting up database schema..."

# Download Cloud SQL Proxy
if [ ! -f "cloud_sql_proxy" ]; then
    echo "⬇️  Downloading Cloud SQL Proxy..."
    curl -o cloud_sql_proxy https://dl.google.com/cloudsql/cloud_sql_proxy.darwin.amd64
    chmod +x cloud_sql_proxy
fi

# Start Cloud SQL Proxy in background
echo "🔌 Starting Cloud SQL Proxy..."
./cloud_sql_proxy -instances=$CONNECTION_NAME=tcp:5432 &
PROXY_PID=$!
sleep 5  # Wait for proxy to start

# Export password for psql
export PGPASSWORD="$DB_PASSWORD"

# Run schema creation
echo "🏗️  Creating database schema..."
psql "host=localhost port=5432 dbname=$DB_NAME user=postgres sslmode=disable" \
    -f "sql/zoho_crm_digital_twin_schema.sql"

# Grant permissions to application user
echo "🔑 Granting permissions to $DB_USER..."
psql "host=localhost port=5432 dbname=$DB_NAME user=postgres sslmode=disable" << EOF
GRANT CONNECT ON DATABASE $DB_NAME TO $DB_USER;
GRANT USAGE ON SCHEMA public TO $DB_USER;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $DB_USER;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
EOF

# Stop Cloud SQL Proxy
kill $PROXY_PID

# Create connection configuration file
echo ""
echo "📄 Creating connection configuration..."
cat > postgres_connection_config.json << EOF
{
  "cloud_sql": {
    "instance_name": "$CONNECTION_NAME",
    "database_name": "$DB_NAME",
    "user": "$DB_USER",
    "password": "$DB_PASSWORD",
    "region": "$REGION"
  },
  "local_development": {
    "host": "localhost",
    "port": 5432,
    "database": "$DB_NAME",
    "user": "$DB_USER",
    "password": "$DB_PASSWORD",
    "sslmode": "disable"
  }
}
EOF

# Create environment file
echo ""
echo "📝 Creating environment file..."
cat > .env.postgres << EOF
# PostgreSQL Connection - Zoho CRM Digital Twin
POSTGRES_HOST="localhost"
POSTGRES_PORT="5432"
POSTGRES_DB="$DB_NAME"
POSTGRES_USER="$DB_USER"
POSTGRES_PASSWORD="$DB_PASSWORD"
POSTGRES_SSL_MODE="disable"
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=20

# Cloud SQL Connection (for production)
CLOUD_SQL_INSTANCE="$CONNECTION_NAME"
CLOUD_SQL_REGION="$REGION"
EOF

# Store password in Google Secret Manager (optional)
echo ""
echo "🔒 Storing password in Secret Manager..."
gcloud secrets create postgres-password --replication-policy="automatic"
echo -n "$DB_PASSWORD" | gcloud secrets versions add postgres-password --data-file=-

# Create service account for Cloud Run
echo ""
echo "👥 Creating service account for Cloud Run..."
gcloud iam service-accounts create zoho-crm-sync-sa \
    --display-name="Zoho CRM Sync Service Account"

# Grant permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:zoho-crm-sync-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/cloudsql.client"

gcloud secrets add-iam-policy-binding postgres-password \
    --member="serviceAccount:zoho-crm-sync-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

echo ""
echo "========================================="
echo "✅ SETUP COMPLETE!"
echo "========================================="
echo ""
echo "📊 Database Information:"
echo "   Instance: $INSTANCE_NAME"
echo "   Database: $DB_NAME"
echo "   User: $DB_USER"
echo "   Password: Saved to Secret Manager"
echo "   Connection: $CONNECTION_NAME"
echo ""
echo "🔧 Next Steps:"
echo "   1. Update .env.crm_sync with PostgreSQL credentials"
echo "   2. Configure Zoho CRM authentication"
echo "   3. Deploy sync service to Cloud Run"
echo ""
echo "📁 Files created:"
echo "   - postgres_connection_config.json"
echo "   - .env.postgres"
echo ""
echo "⚠️  IMPORTANT:"
echo "   - Keep the password secure!"
echo "   - Enable SSL for production"
echo "   - Configure proper backup retention"
echo "   - Set up monitoring and alerts"
echo ""
echo "For local development, use Cloud SQL Proxy:"
echo "  ./cloud_sql_proxy -instances=$CONNECTION_NAME=tcp:5432"
echo ""
echo "To connect via psql:"
echo "  PGPASSWORD='$DB_PASSWORD' psql -h localhost -p 5432 -U $DB_USER -d $DB_NAME"
echo "========================================="