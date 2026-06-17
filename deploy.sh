#!/bin/bash
# Production Deployment Script for vLLM Ascend Dashboard
# Usage: ./deploy.sh [start|stop|restart|logs|backup|migrate|rebuild|status]

# 注意：不使用 set -e，因为我们需要自己控制错误处理逻辑
set -o pipefail  # 管道中任何命令失败都会导致整个管道失败

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.production"
PROJECT_NAME="vllm-dashboard"
BACKUP_DIR="backup"

# Container names (derived from PROJECT_NAME)
MYSQL_CONTAINER="${PROJECT_NAME}-mysql"
BACKEND_CONTAINER="${PROJECT_NAME}-backend"
FRONTEND_CONTAINER="${PROJECT_NAME}-frontend"

# Detect Docker Compose command (prefer 'docker compose' over 'docker-compose')
detect_compose_command() {
    # Prefer Docker Compose plugin (v2.x)
    if command -v docker &> /dev/null; then
        if docker compose version &> /dev/null 2>&1; then
            echo "docker compose"
            return 0
        fi
    fi

    # Fallback to standalone docker-compose (v1.x)
    if command -v docker-compose &> /dev/null; then
        local version_output
        version_output=$(docker-compose --version 2>&1)
        if [[ "$version_output" == *"1."* ]]; then
            log_warn "docker-compose v1.x detected, may have compatibility issues"
        fi
        echo "docker-compose"
        return 0
    fi

    echo ""
    return 1
}

DOCKER_COMPOSE=$(detect_compose_command)

# Global variables
MYSQL_ROOT_PASSWORD=""
FRONTEND_PORT=""

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

check_prerequisites() {
    log_step "Checking prerequisites..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi
    log_info "Docker version: $(docker --version)"

    # Check Docker Compose
    if [ -z "$DOCKER_COMPOSE" ]; then
        log_error "Docker Compose is not installed"
        exit 1
    fi
    log_info "Docker Compose: $($DOCKER_COMPOSE version)"

    # Check environment file
    if [ ! -f "$ENV_FILE" ]; then
        log_error "$ENV_FILE not found"
        log_error "Please copy .env.production.example to $ENV_FILE and configure it"
        exit 1
    fi

    # Validate environment file has required variables
    log_step "Validating environment configuration..."
    local missing_vars=()
    
    # Check critical variables
    for var in GITHUB_TOKEN JWT_SECRET MYSQL_ROOT_PASSWORD MYSQL_PASSWORD; do
        if ! grep -q "^${var}=" "$ENV_FILE" 2>/dev/null; then
            missing_vars+=("$var")
        fi
    done
    
    if [ ${#missing_vars[@]} -gt 0 ]; then
        log_error "Missing required environment variables:"
        for var in "${missing_vars[@]}"; do
            log_error "  - $var"
        done
        log_error "Please update $ENV_FILE with required values"
        exit 1
    fi

    # Load environment variables
    set -a
    source "$ENV_FILE"
    set +a

    # Validate JWT_SECRET length
    if [ ${#JWT_SECRET} -lt 32 ]; then
        log_error "JWT_SECRET must be at least 32 characters long"
        log_error "Generate a secure secret with: openssl rand -hex 32"
        exit 1
    fi

    # Set global variables
    MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-}"
    FRONTEND_PORT="${FRONTEND_PORT:-3000}"

    log_success "Prerequisites check passed"
}

wait_for_mysql() {
    log_step "Waiting for MySQL to be ready..."
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        # Use --password= to handle special characters in password
        if [ -z "$MYSQL_ROOT_PASSWORD" ]; then
            # Empty password
            if docker exec "$MYSQL_CONTAINER" mysqladmin ping -h localhost -u root &>/dev/null; then
                log_success "MySQL is ready"
                return 0
            fi
        else
            if docker exec "$MYSQL_CONTAINER" mysqladmin ping -h localhost -u root "--password=${MYSQL_ROOT_PASSWORD}" &>/dev/null; then
                log_success "MySQL is ready"
                return 0
            fi
        fi
        log_info "Waiting for MySQL... ($attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "MySQL failed to start after $max_attempts attempts"
    return 1
}

wait_for_backend() {
    log_step "Waiting for backend to be ready..."
    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        # Use Python instead of curl (more reliable in minimal containers)
        if docker exec "$BACKEND_CONTAINER" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" &>/dev/null; then
            log_success "Backend is ready"
            return 0
        fi
        log_info "Waiting for backend... ($attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "Backend failed to start after $max_attempts attempts"
    return 1
}

deploy() {
    log_step "Deploying vLLM Ascend Dashboard..."

    # Start services
    if ! $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE --profile full up -d --build; then
        log_error "Failed to start services"
        return 1
    fi

    # Wait for services
    if ! wait_for_mysql; then
        log_error "MySQL startup failed"
        return 1
    fi

    if ! wait_for_backend; then
        log_error "Backend startup failed"
        return 1
    fi

    # Run database initialization
    log_step "Running database initialization..."
    docker exec -w /app -e PYTHONPATH=/app "$BACKEND_CONTAINER" python scripts/init_db.py || {
        log_warn "Database initialization skipped (may already be initialized)"
    }

    log_success "Deployment complete!"
    show_status

    echo ""
    log_info "If this is a fresh installation, default admin credentials:"
    echo "  Username: admin"
    echo "  Password: admin123"
    echo ""
    log_warn "IMPORTANT: Please change the default password after first login!"
    log_warn "See /docs/SECURITY.md for security best practices."
}

# Database migration function
migrate_database() {
    log_step "Running database migration..."

    # Wait for services (if not already running)
    if ! wait_for_mysql; then
        return 1
    fi

    if ! wait_for_backend; then
        return 1
    fi

    # Run migration script (automatically upgrades to latest version)
    log_info "Executing database upgrade to latest version..."
    # Set PYTHONPATH to include /app directory so 'app' module can be imported
    if docker exec -w /app -e PYTHONPATH=/app "$BACKEND_CONTAINER" python scripts/upgrade_db.py; then
        log_success "Database upgrade completed successfully!"
        return 0
    else
        log_error "Database upgrade failed!"
        return 1
    fi
}

stop_services() {
    log_step "Stopping all services..."
    $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE --profile full down
    log_success "All services stopped"
}

restart_services() {
    log_step "Restarting all services..."
    $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE restart
    if wait_for_backend; then
        show_status
        return 0
    else
        return 1
    fi
}

show_logs() {
    local service=$1
    if [ -n "$service" ]; then
        $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE logs -f "$service"
    else
        $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE logs -f
    fi
}

show_status() {
    echo ""
    log_info "Service Status:"
    $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE --profile full ps
    echo ""
    log_info "Access URL:"
    echo "  Frontend (with API proxy): http://localhost:${FRONTEND_PORT:-3000}"
    echo ""
    log_info "Note: Backend API is proxied through Nginx at /api path"
    log_info "      Only port ${FRONTEND_PORT:-3000} is exposed to public"
}

backup_data() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_path="$BACKUP_DIR/$timestamp"
    local backup_failed=false

    log_step "Creating backup in $backup_path..."
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$backup_path"

    # Load environment variables (only if not already loaded)
    if [ -z "$MYSQL_ROOT_PASSWORD" ] && [ -f "$ENV_FILE" ]; then
        set -a
        source "$ENV_FILE"
        set +a
        MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-}"
    fi

    # Backup MySQL database
    if docker ps --format '{{.Names}}' | grep -q "$MYSQL_CONTAINER"; then
        log_info "Backing up MySQL database..."
        # Use --password= to handle special characters in password
        if [ -z "$MYSQL_ROOT_PASSWORD" ]; then
            # Empty password
            if docker exec "$MYSQL_CONTAINER" mysqldump \
                -u root \
                --single-transaction \
                --quick \
                --lock-tables=false \
                vllm_dashboard > "$backup_path/mysql_backup.sql" 2>/dev/null; then
                log_success "MySQL backup completed"
            else
                log_warn "MySQL backup failed"
                backup_failed=true
            fi
        else
            if docker exec "$MYSQL_CONTAINER" mysqldump \
                -u root "--password=${MYSQL_ROOT_PASSWORD}" \
                --single-transaction \
                --quick \
                --lock-tables=false \
                vllm_dashboard > "$backup_path/mysql_backup.sql" 2>/dev/null; then
                log_success "MySQL backup completed"
            else
                log_warn "MySQL backup failed"
                backup_failed=true
            fi
        fi
    fi

    # Backup backend data (SQLite, if used)
    if docker ps --format '{{.Names}}' | grep -q "$BACKEND_CONTAINER"; then
        log_info "Backing up backend data..."
        local temp_file="/tmp/backend_backup_$timestamp.tar.gz"
        if docker exec "$BACKEND_CONTAINER" tar -czf "$temp_file" /app/data 2>/dev/null; then
            if docker cp "$BACKEND_CONTAINER":"$temp_file" "$backup_path/" 2>/dev/null; then
                log_success "Backend backup completed"
            else
                log_warn "Backend backup copy failed"
                backup_failed=true
            fi
        else
            log_warn "Backend backup creation failed"
            backup_failed=true
        fi
    fi

    # Check if we have any backups
    if [ "$(ls -A "$backup_path" 2>/dev/null)" ]; then
        # Compress backup
        local final_backup="$backup_path.tar.gz"
        if tar -czf "$final_backup" -C "$(dirname "$backup_path")" "$(basename "$backup_path")"; then
            rm -rf "$backup_path"
            log_success "Backup completed: $final_backup"
            if [ "$backup_failed" = true ]; then
                log_warn "Some backup components failed, but backup file was created"
            fi
            return 0
        else
            log_error "Failed to compress backup"
            return 1
        fi
    else
        # 容器不在运行或没有可备份的数据：不阻塞升级
        log_warn "No containers found or no data to backup"
        log_warn "Docker volumes are persistent and will survive the upgrade"
        rm -rf "$backup_path"
        return 0
    fi
}

# Upgrade function (NEW - complete upgrade process)
upgrade() {
    log_step "Starting upgrade process..."
    echo ""
    echo "========================================"
    echo "  vLLM Ascend Dashboard Upgrade"
    echo "  Features: Model Board + Official Doc URL"
    echo "========================================"
    echo ""

    local upgrade_failed=false

    # 1. Backup
    log_step "Step 1/4: Creating backup..."
    if ! backup_data; then
        log_error "Backup failed! Upgrade aborted."
        log_warn "Your data is still safe, but please fix the backup issue before upgrading"
        return 1
    fi

    # 2. Stop services
    log_step "Step 2/4: Stopping services..."
    if ! stop_services; then
        log_error "Stop services failed!"
        log_warn "Please manually stop services with '$0 stop' before upgrading"
        return 1
    fi

    # 3. Rebuild and start
    log_step "Step 3/4: Rebuilding services..."
    if ! $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE --profile full up -d --build; then
        log_error "Failed to rebuild services"
        return 1
    fi

    # 4. Run migration
    log_step "Step 4/4: Running database migration..."
    if ! migrate_database; then
        log_error "Database migration failed!"
        log_warn "Services are still running, but database may be in inconsistent state"
        log_warn "Consider restoring from backup: $BACKUP_DIR/"
        upgrade_failed=true
    fi

    echo ""
    echo "========================================"
    if [ "$upgrade_failed" = false ]; then
        log_success "Upgrade completed successfully!"
    else
        log_warn "Upgrade completed with errors"
    fi
    echo "========================================"
    echo ""
    show_status

    if [ "$upgrade_failed" = true ]; then
        return 1
    fi
    return 0
}

show_help() {
    echo ""
    echo "========================================"
    echo "  vLLM Ascend Dashboard - Deployment Script"
    echo "  Version: v0.0.1"
    echo "========================================"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start          Deploy or upgrade the application"
    echo "  stop           Stop all services"
    echo "  restart        Restart all services"
    echo "  logs [service] Show logs (optionally filter by service)"
    echo "  status         Show service status"
    echo "  backup         Backup data (MySQL + backend)"
    echo "  migrate        Run database migration only"
    echo "  upgrade        Complete upgrade process (backup → stop → rebuild → migrate)"
    echo "  rebuild        Rebuild and restart all services"
    echo "  help           Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start       # Start or upgrade"
    echo "  $0 upgrade     # Full upgrade process"
    echo "  $0 migrate     # Run database migration"
    echo "  $0 backup      # Create backup"
    echo "  $0 logs backend"
    echo "  $0 status"
    echo ""
    echo "========================================"
    echo ""
    echo "Automatic Upgrade:"
    echo "  The 'upgrade' and 'migrate' commands will automatically:"
    echo "  1. Detect current database version"
    echo "  2. Find all available upgrade scripts (upgrade_v*.py)"
    echo "  3. Apply upgrades in version order"
    echo "  4. Record each version in database_versions table"
    echo ""
    echo "  Example upgrade path:"
    echo "    v0.0.0 → v0.0.1 → v0.0.2 → ..."
    echo ""
    echo "  Creating new upgrades:"
    echo "  1. Create backend/scripts/upgrade_vX.Y.Z.py"
    echo "  2. Define async upgrade() function"
    echo "  3. Run '$0 upgrade' to apply"
    echo ""
    echo "========================================"
    echo ""
}

# Main command handler
case "${1:-help}" in
    start)
        check_prerequisites
        deploy
        ;;
    stop)
        check_prerequisites
        stop_services
        ;;
    restart)
        check_prerequisites
        restart_services
        ;;
    logs)
        show_logs "$2"
        ;;
    status)
        check_prerequisites
        show_status
        ;;
    backup)
        check_prerequisites
        backup_data
        ;;
    migrate)
        check_prerequisites
        migrate_database
        ;;
    upgrade)
        check_prerequisites
        upgrade
        ;;
    rebuild)
        check_prerequisites
        log_info "Rebuilding all services..."
        $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE down
        $DOCKER_COMPOSE -f $COMPOSE_FILE --env-file $ENV_FILE --profile full up -d --build
        # Wait for MySQL first, then backend
        if wait_for_mysql && wait_for_backend; then
            show_status
        else
            exit 1
        fi
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
