#!/bin/bash
set -e

cd "$(dirname "$0")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "Setting up ai-for-investor development environment..."

setup_backend() {
    log "Setting up backend..."
    cd backend

    if [ ! -f ".env" ]; then
        log "Creating .env from .env.example..."
        cp .env.example .env
        log "Please edit .env and configure your database connection"
    fi

    if [ ! -d "venv" ]; then
        log "Creating Python virtual environment..."
        python3 -m venv venv
    fi

    log "Activating virtual environment..."
    source venv/bin/activate

    log "Installing Python dependencies..."
    pip install -r requirements.txt

    cd ..
    log "Backend setup complete!"
}

setup_frontend() {
    log "Setting up frontend..."
    cd frontend

    if [ ! -f "package.json" ]; then
        log "Error: package.json not found"
        cd ..
        return 1
    fi

    log "Installing Node.js dependencies..."
    npm install

    cd ..
    log "Frontend setup complete!"
}

setup_database() {
    log "Setting up database..."

    source backend/venv/bin/activate 2>/dev/null || true

    log "Please ensure MySQL, MongoDB, and Redis are running locally"
    log "Create the MySQL database:"
    log "  CREATE DATABASE ai_for_investor CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    log "  CREATE USER 'ai_for_investor'@'localhost' IDENTIFIED BY 'your_password';"
    log "  GRANT ALL PRIVILEGES ON ai_for_investor.* TO 'ai_for_investor'@'localhost';"
    log "  FLUSH PRIVILEGES;"

    log "Database setup instructions provided above"
}

log "========================================="
log "   ai-for-investor Setup Script"
log "========================================="

echo ""
echo "1) Setup Backend (Python/FastAPI)"
echo "2) Setup Frontend (Node.js/Nuxt)"
echo "3) Setup Database (MySQL/MongoDB/Redis instructions)"
echo "4) Full Setup (Backend + Frontend)"
echo "5) Exit"
echo ""

read -p "Select an option (1-5): " choice

case $choice in
    1)
        setup_backend
        ;;
    2)
        setup_frontend
        ;;
    3)
        setup_database
        ;;
    4)
        setup_backend
        setup_frontend
        setup_database
        log "Full setup complete!"
        ;;
    5)
        log "Setup cancelled"
        exit 0
        ;;
    *)
        log "Invalid option: $choice"
        exit 1
        ;;
esac

log "Setup complete!"
log "Run ./start_app.sh to start the application"
