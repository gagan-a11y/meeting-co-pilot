#!/bin/bash

# Easy deployment script for Meeting App Docker container
# 
# ⚠️  AUDIO PROCESSING WARNING:
# Insufficient Docker resources cause audio drops! The audio processing system
# drops chunks when queue is full (MAX_AUDIO_QUEUE_SIZE=10, lib.rs:54).
# Symptoms: "Dropped old audio chunk" in logs (lib.rs:330-333).
# Solution: Allocate 8GB+ RAM and adequate CPU to Docker containers.

set -e

# Configuration
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_PROJECT_NAME="meeting-app"
APP_CONTAINER_NAME="meeting-copilot-backend"
DEFAULT_APP_PORT=5167
PREFERENCES_FILE="$SCRIPT_DIR/.docker-preferences"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to run docker compose with the correct command
docker_compose() {
    if command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    elif docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    else
        log_error "Neither 'docker-compose' nor 'docker compose' command found"
        return 1
    fi
}

# Ensure required directories exist
ensure_directories() {
    # Create data directory for database if it doesn't exist
    if [ ! -d "$SCRIPT_DIR/data" ]; then
        log_info "Creating data directory for database..."
        mkdir -p "$SCRIPT_DIR/data"
        chmod 755 "$SCRIPT_DIR/data"
        log_info "✓ Data directory created"
    fi
}

# Initialize fresh database file
init_fresh_database() {
    local db_path="$SCRIPT_DIR/data/meeting_minutes.db"
    if [ ! -f "$db_path" ]; then
        log_info "Initializing fresh database..."
        # Create an empty database file with proper permissions
        touch "$db_path"
        chmod 644 "$db_path"
        log_info "✓ Fresh database initialized at: $db_path"
    fi
}

# Ensure directories exist on script start
ensure_directories

# Initialize fresh database if it doesn't exist
init_fresh_database

# Platform detection for macOS support
DETECTED_OS=$(uname -s)
IS_MACOS=false
COMPOSE_PROFILE_ARGS=()
if [[ "$DETECTED_OS" == "Darwin" ]]; then
    IS_MACOS=true
    COMPOSE_PROFILE_ARGS=("--profile" "macos")
    log_info "macOS detected - will use macOS-optimized Docker services"
else
    # Use default profile for Linux/Windows
    COMPOSE_PROFILE_ARGS=("--profile" "default")
fi

# Function to load saved preferences
load_preferences() {
    if [ ! -f "$PREFERENCES_FILE" ]; then
        return 1
    fi
    
    # Source the preferences file safely
    if source "$PREFERENCES_FILE" 2>/dev/null; then
        return 0
    else
        log_warn "Invalid preferences file, will use defaults"
        return 1
    fi
}

# Function to save current preferences
save_preferences() {
    local app_port="$1"
    
    cat > "$PREFERENCES_FILE" << EOF
# Docker run preferences - automatically generated
# Last updated: $(date)
SAVED_APP_PORT="$app_port"
EOF
    
    log_info "✓ Preferences saved to $PREFERENCES_FILE"
}

show_help() {
    cat << EOF
Meeting App Docker Deployment Script

Usage: $0 [COMMAND] [OPTIONS]

COMMANDS:
  start         Start meeting app
  stop          Stop running services
  restart       Restart services
  logs          Show service logs
  status        Show service status
  clean         Remove containers and images
  build         Build Docker images
  setup-db      Setup/migrate database from existing installation
  compose       Pass commands directly to docker_compose

START OPTIONS:
  --app-port PORT         Meeting app port to expose (default: 5167)
  -d, --detach            Run in background
  --env-file FILE         Load environment from file

LOG OPTIONS:
  -f, --follow           Follow log output
  -n, --lines N          Number of lines to show (default: 100)

GLOBAL OPTIONS:
  --dry-run               Show commands without executing
  -h, --help              Show this help

Examples:
  # Start with default settings
  $0 start
  
  # Start on custom port in background
  $0 start --app-port 8000 --detach
  
  # View logs
  $0 logs -f
  
  # Stop services
  $0 stop
EOF
}

# Function to check if port is available
check_port_available() {
    local port="$1"
    if lsof -i ":$port" | grep -q LISTEN 2>/dev/null; then
        return 1  # Port is in use
    else
        return 0  # Port is available
    fi
}

# Function to select meeting app port
select_app_port() {
    local default_port="${1:-5167}"
    
    echo -e "${BLUE}=== Meeting App Port Selection ===${NC}" >&2
    echo -e "${GREEN}Choose Meeting app port:${NC}" >&2
    echo "  Current: $default_port" >&2
    echo "  Common alternatives: 5168, 5169, 3000, 8000" >&2
    echo >&2
    
    while true; do
        echo -ne "${YELLOW}Enter Meeting app port [default: $default_port]: ${NC}" >&2
        read port_choice
        
        # Default to saved preference if empty
        if [[ -z "$port_choice" ]]; then
            echo "$default_port"
            return
        fi
        
        # Validate port number
        if [[ "$port_choice" =~ ^[0-9]+$ ]] && [[ $port_choice -ge 1024 && $port_choice -le 65535 ]]; then
            if check_port_available "$port_choice"; then
                echo "$port_choice"
                return
            else
                echo -e "${RED}Port $port_choice is already in use.${NC}" >&2
                echo -ne "${YELLOW}Kill the process using this port? (y/N): ${NC}" >&2
                read kill_choice
                if [[ "$kill_choice" =~ ^[Yy] ]]; then
                    if lsof -ti ":$port_choice" | xargs kill -9 2>/dev/null; then
                        echo -e "${GREEN}Port $port_choice is now available.${NC}" >&2
                        echo "$port_choice"
                        return
                    else
                        echo -e "${RED}Failed to free port $port_choice.${NC}" >&2
                    fi
                fi
            fi
        else
            echo -e "${RED}Invalid port. Please enter a number between 1024-65535.${NC}" >&2
        fi
    done
}

# Function to show service status
show_status() {
    echo -e "${BLUE}=== Service Status ===${NC}"
    if command -v docker-compose >/dev/null 2>&1 || docker compose version >/dev/null 2>&1; then
        docker_compose "${COMPOSE_PROFILE_ARGS[@]}" ps
    else
        docker ps --filter "name=${APP_CONTAINER_NAME}"
    fi
}

# Main command handling
command="${1:-start}"
shift || true

case "$command" in
    start)
        # Parse arguments
        app_port="$DEFAULT_APP_PORT"
        detach=false
        env_file=""
        
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --app-port) app_port="$2"; shift 2 ;;
                -d|--detach) detach=true; shift ;;
                --env-file) env_file="$2"; shift 2 ;;
                *) echo "Unknown option: $1"; show_help; exit 1 ;;
            esac
        done
        
        log_info "Starting Meeting App on port $app_port..."
        
        # Determine service name based on OS
        service_name="meeting-copilot-backend"
        if [ "$IS_MACOS" = true ]; then
            service_name="meeting-copilot-backend-macos"
        fi
        
        # Start command
        export APP_PORT="$app_port"
        
        if [ "$detach" = true ]; then
            docker_compose "${COMPOSE_PROFILE_ARGS[@]}" up -d ${env_file:+--env-file "$env_file"} "$service_name"
        else
            docker_compose "${COMPOSE_PROFILE_ARGS[@]}" up ${env_file:+--env-file "$env_file"} "$service_name"
        fi
        
        save_preferences "$app_port"
        ;;
        
    stop)
        log_info "Stopping services..."
        docker_compose "${COMPOSE_PROFILE_ARGS[@]}" down
        ;;
        
    restart)
        log_info "Restarting services..."
        docker_compose "${COMPOSE_PROFILE_ARGS[@]}" restart
        ;;
        
    logs)
        follow=false
        lines=100
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -f|--follow) follow=true; shift ;;
                -n|--lines) lines="$2"; shift 2 ;;
                *) echo "Unknown option: $1"; shift ;;
            esac
        done
        
        cmd=("docker_compose" "${COMPOSE_PROFILE_ARGS[@]}" "logs" "--tail=$lines")
        if [ "$follow" = true ]; then
            cmd+=("-f")
        fi
        "${cmd[@]}"
        ;;
        
    status)
        show_status
        ;;
        
    clean)
        log_info "Removing containers and images..."
        docker_compose "${COMPOSE_PROFILE_ARGS[@]}" down --rmi all --volumes --remove-orphans
        ;;
        
    build)
        log_info "Building Docker images..."
        docker_compose "${COMPOSE_PROFILE_ARGS[@]}" build
        ;;
        
    setup-db)
        log_info "Setting up database..."
        # Add db setup logic if needed
        ;;
        
    compose)
        docker_compose "${COMPOSE_PROFILE_ARGS[@]}" "$@"
        ;;
        
    -h|--help)
        show_help
        ;;
        
    *)
        log_error "Unknown command: $command"
        show_help
        exit 1
        ;;
esac

# Function to check if database exists and is valid
check_database() {
    local db_path="$1"
    if [ ! -f "$db_path" ]; then
        return 1
    fi
    return 0
}