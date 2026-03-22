#!/bin/bash
# Test the remake CLI

set -e

PLATFORM_URL="http://localhost:5000"
USER_EMAIL="test@example.com"

echo "========================================"
echo "Testing Remake CLI"
echo "========================================"
echo

# Auto-approve pairing requests in background
auto_approve() {
    sleep 3
    # Get pending requests and approve the first one
    REQ_ID=$(curl -s "$PLATFORM_URL/api/pairing-requests" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['requests'][0]['id'] if d.get('requests') else '')" 2>/dev/null)
    if [ -n "$REQ_ID" ]; then
        echo "  [Auto-approve] Approving $REQ_ID..."
        curl -s -X POST "$PLATFORM_URL/api/robot-pairing/$REQ_ID/approve" > /dev/null
        echo "  [Auto-approve] Done"
    fi
}

echo "=== Test 1: remake status (before pairing) ==="
remake status
echo

echo "=== Test 2: remake pair ==="
auto_approve &
APPROVE_PID=$!

# Use expect-like input for the email prompt
echo "$USER_EMAIL" | remake pair \
    --platform "$PLATFORM_URL" \
    --name "CLI Test Robot" \
    --timeout 15

wait $APPROVE_PID 2>/dev/null || true
echo

echo "=== Test 3: remake status (after pairing) ==="
remake status
echo

echo "=== Test 4: remake app list ==="
remake app list --platform "$PLATFORM_URL"
echo

echo "=== Test 5: remake connect (5 seconds) ==="
timeout 5 remake connect --platform "$PLATFORM_URL" || true
echo

echo "=== Test 6: remake unpair ==="
remake unpair --force
echo

echo "=== Test 7: remake status (after unpair) ==="
remake status
echo

echo "========================================"
echo "CLI Tests Complete"
echo "========================================"
