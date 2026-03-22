#!/bin/bash
# V2 Backend Integration Test Harness
# Automates: database setup, backend launch, robot client, API calls

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$HOME/appstore/backend"
DB_PATH="$BACKEND_DIR/app.db"

# Test robot credentials
ROBOT_ID="test-robot-v2-001"
ROBOT_SECRET="test-secret-v2-001"
TEST_USER_ID="test-user-001"
TEST_APP_ID="com.test.app"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[TEST]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

cleanup() {
    log "Cleaning up..."
    # Kill background processes
    if [ -n "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ -n "$CLIENT_PID" ]; then
        kill $CLIENT_PID 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Step 1: Provision test data in database
provision_test_data() {
    log "Provisioning test data in database..."
    cd "$BACKEND_DIR"

    ROBOT_ID="$ROBOT_ID" ROBOT_SECRET="$ROBOT_SECRET" node scripts/provision-test-robot.js

    log "Test data provisioned: robot=$ROBOT_ID, app=$TEST_APP_ID"
}

# Step 2: Start backend
start_backend() {
    log "Starting backend server..."
    cd "$BACKEND_DIR"

    # Start with BYPASS_AUTH for easier testing
    BYPASS_AUTH=true node server-refactored.js > /tmp/backend-test.log 2>&1 &
    BACKEND_PID=$!

    # Wait for server to be ready
    log "Waiting for backend to start (PID: $BACKEND_PID)..."
    for i in {1..30}; do
        if curl -s http://localhost:5000/health > /dev/null 2>&1; then
            log "Backend is ready!"
            return 0
        fi
        sleep 0.5
    done

    error "Backend failed to start. Check /tmp/backend-test.log"
    cat /tmp/backend-test.log | tail -20
    return 1
}

# Step 3: Run robot client in background
start_robot_client() {
    log "Starting robot client..."
    cd "$SDK_DIR"

    # Install SDK if needed
    if ! python3 -c "import remake_sdk" 2>/dev/null; then
        log "Installing remake-sdk..."
        pip install -e ".[platform]" > /dev/null 2>&1
    fi

    ROBOT_ID="$ROBOT_ID" ROBOT_SECRET="$ROBOT_SECRET" \
        python3 examples/test_v2_backend.py > /tmp/robot-client.log 2>&1 &
    CLIENT_PID=$!

    # Wait for client to connect
    log "Waiting for robot client to connect (PID: $CLIENT_PID)..."
    sleep 3

    if ! kill -0 $CLIENT_PID 2>/dev/null; then
        error "Robot client failed to start. Check /tmp/robot-client.log"
        cat /tmp/robot-client.log
        return 1
    fi

    log "Robot client running!"
}

# Step 4: Test the v2 endpoints
run_tests() {
    log "Running v2 endpoint tests..."

    # Test 1: Robot status
    log "Test 1: GET /api/v2/robots/$ROBOT_ID/status"
    RESULT=$(curl -s "http://localhost:5000/api/v2/robots/$ROBOT_ID/status" \
        -H "Content-Type: application/json")
    echo "  Response: $RESULT"

    if echo "$RESULT" | grep -q '"success":true'; then
        log "  PASSED"
    else
        error "  FAILED"
    fi

    # Test 2: List installed apps
    log "Test 2: GET /api/v2/robots/$ROBOT_ID/apps"
    RESULT=$(curl -s "http://localhost:5000/api/v2/robots/$ROBOT_ID/apps" \
        -H "Content-Type: application/json")
    echo "  Response: $RESULT"

    # Test 3: Launch app
    log "Test 3: POST /api/v2/robots/$ROBOT_ID/apps/$TEST_APP_ID/launch"
    RESULT=$(curl -s -X POST "http://localhost:5000/api/v2/robots/$ROBOT_ID/apps/$TEST_APP_ID/launch" \
        -H "Content-Type: application/json")
    echo "  Response: $RESULT"

    if echo "$RESULT" | grep -q '"success":true'; then
        log "  Launch command sent!"

        # Give time for WebSocket round-trip
        sleep 2

        # Check robot client log for received command
        if grep -q "RECEIVED APP COMMAND" /tmp/robot-client.log 2>/dev/null; then
            log "  Robot received launch command - PASSED"
        else
            warn "  Robot may not have received command (check /tmp/robot-client.log)"
        fi
    else
        error "  Launch command failed"
    fi

    # Test 4: Stop app
    log "Test 4: POST /api/v2/robots/$ROBOT_ID/apps/$TEST_APP_ID/stop"
    RESULT=$(curl -s -X POST "http://localhost:5000/api/v2/robots/$ROBOT_ID/apps/$TEST_APP_ID/stop" \
        -H "Content-Type: application/json")
    echo "  Response: $RESULT"

    # Test 5: Launch history
    log "Test 5: GET /api/v2/robots/$ROBOT_ID/launches"
    RESULT=$(curl -s "http://localhost:5000/api/v2/robots/$ROBOT_ID/launches" \
        -H "Content-Type: application/json")
    echo "  Response: $RESULT"
}

# Main
main() {
    log "======================================"
    log "V2 Backend Integration Test"
    log "======================================"

    # Check prerequisites
    if [ ! -f "$DB_PATH" ]; then
        error "Database not found at $DB_PATH"
        error "Please run the backend once to initialize the database"
        exit 1
    fi

    provision_test_data
    start_backend
    start_robot_client

    echo ""
    run_tests
    echo ""

    log "======================================"
    log "Test Summary"
    log "======================================"
    log "Backend log: /tmp/backend-test.log"
    log "Client log:  /tmp/robot-client.log"
    log "======================================"

    # Keep running for manual inspection
    log "Press Enter to shutdown..."
    read
}

main "$@"
