#!/usr/bin/env python3
"""
Test script for robot pairing flow.

Flow:
1. Robot connects (unauthenticated)
2. Robot sends pair_cmd with user email
3. Server creates pairing request, returns 'pending'
4. User approves via REST API
5. Robot receives credentials via get_pairing_status
6. Robot authenticates with new credentials

Usage:
    python test_pairing.py
"""

import asyncio
import os
import sys
import uuid
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import socketio

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:5000")
USER_EMAIL = os.environ.get("USER_EMAIL", "test@example.com")
ROBOT_NAME = os.environ.get("ROBOT_NAME", "Test Robot Pairing")
NAMESPACE = "/robot-control"


async def main():
    print(f"Testing pairing flow...")
    print(f"  Platform: {PLATFORM_URL}")
    print(f"  User: {USER_EMAIL}")
    print(f"  Robot: {ROBOT_NAME}")
    print()

    # Create Socket.IO client
    sio = socketio.AsyncClient(logger=False, engineio_logger=False)

    # State
    pairing_result = {}
    credentials = {}
    events_received = []

    @sio.on("connect", namespace=NAMESPACE)
    async def on_connect():
        print("[1] Connected to server")
        events_received.append("connect")

    @sio.on("disconnect", namespace=NAMESPACE)
    async def on_disconnect():
        print("[x] Disconnected")

    @sio.on("pair_response", namespace=NAMESPACE)
    async def on_pair_response(data):
        print(f"[3] Received pair_response: {data}")
        pairing_result.update(data)
        events_received.append("pair_response")

    @sio.on("pairing_approved", namespace=NAMESPACE)
    async def on_pairing_approved(data):
        print(f"[5] Pairing approved! Credentials: robot_id={data.get('robot_id')}")
        credentials.update(data)
        events_received.append("pairing_approved")

    @sio.on("pairing_denied", namespace=NAMESPACE)
    async def on_pairing_denied(data):
        print(f"[!] Pairing denied: {data}")
        events_received.append("pairing_denied")

    @sio.on("get_pairing_status_response", namespace=NAMESPACE)
    async def on_status_response(data):
        print(f"[4b] Pairing status: {data}")
        if data.get("status") == "approved":
            credentials.update(data)
        events_received.append("get_pairing_status_response")

    try:
        # Step 1: Connect
        print("\n--- Step 1: Connecting ---")
        await sio.connect(PLATFORM_URL, namespaces=[NAMESPACE], transports=["websocket"])
        await asyncio.sleep(1)

        # Step 2: Send pairing request
        print("\n--- Step 2: Requesting pairing ---")
        cmd_id = str(uuid.uuid4())
        await sio.emit("pair_cmd", {
            "cmd_id": cmd_id,
            "method": "approval",
            "username": USER_EMAIL,
            "robot_name": ROBOT_NAME
        }, namespace=NAMESPACE)

        # Wait for pair_response
        await asyncio.sleep(2)

        if pairing_result.get("status") != "pending":
            print(f"[!] Expected 'pending', got: {pairing_result}")
            return

        print(f"\n[OK] Pairing request created, expires at: {pairing_result.get('expires_at')}")

        # Step 3: Simulate user approval via REST API
        print("\n--- Step 3: Simulating user approval ---")

        # Get pending requests
        requests_resp = requests.get(f"{PLATFORM_URL}/api/pairing-requests")
        if requests_resp.status_code == 200:
            pending = requests_resp.json()
            print(f"  Pending requests: {pending}")

        # Since BYPASS_AUTH is on, we can directly approve
        # First, let's find the request ID from the database via another endpoint
        # or we can use the robot-pairing approval endpoint

        # The request_id should be broadcast - let's check the pairing_requests endpoint
        # For now, let's query the pending requests

        # Try to find and approve the request
        print("  Looking for pairing request to approve...")

        # The server broadcasts 'robot_pairing_request' to all clients
        # but we need to get the request_id somehow
        # Let's check if there's a way to get it

        # Actually, we can poll get_pairing_status
        print("\n--- Step 4: Polling for approval ---")
        print("  (In real scenario, user would approve via frontend)")
        print("  Sending get_pairing_status...")

        status_cmd_id = str(uuid.uuid4())
        await sio.emit("get_pairing_status", {
            "cmd_id": status_cmd_id,
            "username": USER_EMAIL
        }, namespace=NAMESPACE)

        await asyncio.sleep(2)

        # For automated test, we need to approve via API
        # Let's try the robot-pairing approve endpoint
        # We need to get the request ID first

        print("\n--- Attempting automated approval ---")

        # Query database for the pending request (using a test endpoint)
        # Since we don't have direct DB access, let's create a simple flow:
        # We'll add a test endpoint or use what we have

        # Check the api/pairing-requests for pending requests
        # This needs authentication in non-BYPASS mode

        print("\nTo complete the test manually:")
        print(f"  1. Go to {PLATFORM_URL} and log in as {USER_EMAIL}")
        print("  2. Approve the pending pairing request")
        print("  3. The robot will receive credentials")
        print("\nOr run this curl command to approve:")
        print(f'  curl -X POST "{PLATFORM_URL}/api/robot-pairing/<request_id>/approve"')

        print("\n--- Waiting for approval (30 seconds) ---")
        print("Press Ctrl+C to exit early.")

        for i in range(30):
            if "pairing_approved" in events_received or credentials.get("robot_id"):
                break

            # Poll status every 3 seconds
            if i > 0 and i % 3 == 0:
                await sio.emit("get_pairing_status", {
                    "cmd_id": str(uuid.uuid4()),
                    "username": USER_EMAIL
                }, namespace=NAMESPACE)

            await asyncio.sleep(1)
            print(f"  Waiting... {30-i}s remaining", end="\r")

        print()

        if credentials.get("robot_id"):
            print("\n" + "="*50)
            print("PAIRING SUCCESSFUL!")
            print("="*50)
            print(f"  Robot ID: {credentials.get('robot_id')}")
            print(f"  Robot Secret: {credentials.get('robot_secret', '(hidden)')[:20]}...")
            print("\nThese credentials can now be used for authentication.")
        else:
            print("\n[!] Pairing not completed within timeout")
            print(f"  Events received: {events_received}")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        await sio.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
