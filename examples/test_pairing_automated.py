#!/usr/bin/env python3
"""
Fully automated test for robot pairing and authentication flow.

Tests:
1. Robot connects (unauthenticated)
2. Robot sends pair_cmd
3. User approves via REST API
4. Robot receives credentials
5. Robot disconnects and reconnects with credentials
6. Robot authenticates successfully

Usage:
    python test_pairing_automated.py
"""

import asyncio
import os
import sys
import uuid
import hmac
import hashlib
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import socketio

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:5000")
USER_EMAIL = "test@example.com"  # Must match BYPASS_AUTH mock user
ROBOT_NAME = f"Test Robot {uuid.uuid4().hex[:6]}"
NAMESPACE = "/robot-control"


class PairingTest:
    def __init__(self):
        self.sio = None
        self.pairing_result = {}
        self.credentials = {}
        self.auth_result = {}
        self.events = []

    async def run_pairing_phase(self):
        """Phase 1: Connect and request pairing."""
        print("\n" + "="*60)
        print("PHASE 1: PAIRING")
        print("="*60)

        self.sio = socketio.AsyncClient(logger=False, engineio_logger=False)

        @self.sio.on("connect", namespace=NAMESPACE)
        async def on_connect():
            print("  [1] Connected to server (unauthenticated)")
            self.events.append("connect")

        @self.sio.on("pair_response", namespace=NAMESPACE)
        async def on_pair_response(data):
            print(f"  [3] pair_response: status={data.get('status')}")
            self.pairing_result.update(data)
            self.events.append("pair_response")

        @self.sio.on("pair_status_event", namespace=NAMESPACE)
        async def on_pair_status(data):
            print(f"  [5] pair_status_event: status={data.get('status')}")
            if data.get("robot_id"):
                self.credentials["robot_id"] = data["robot_id"]
                self.credentials["robot_secret"] = data["robot_secret"]
                print(f"      Robot ID: {data['robot_id']}")
            self.events.append("pair_status_event")

        # Connect
        print("\n  Connecting...")
        await self.sio.connect(PLATFORM_URL, namespaces=[NAMESPACE], transports=["websocket"])
        await asyncio.sleep(1)

        # Request pairing
        print(f"\n  [2] Sending pair_cmd (user={USER_EMAIL}, robot={ROBOT_NAME})")
        cmd_id = str(uuid.uuid4())
        await self.sio.emit("pair_cmd", {
            "cmd_id": cmd_id,
            "method": "approval",
            "username": USER_EMAIL,
            "robot_name": ROBOT_NAME
        }, namespace=NAMESPACE)

        await asyncio.sleep(2)

        if self.pairing_result.get("status") != "pending":
            print(f"  [FAIL] Expected 'pending', got: {self.pairing_result}")
            return False

        print("  [OK] Pairing request created")
        return True

    async def approve_pairing(self):
        """Phase 2: Find and approve the pairing request via REST API."""
        print("\n" + "="*60)
        print("PHASE 2: USER APPROVAL (via REST API)")
        print("="*60)

        # Get pending pairing requests
        print("\n  [4] Getting pending pairing requests...")
        resp = requests.get(f"{PLATFORM_URL}/api/pairing-requests")

        if resp.status_code != 200:
            print(f"  [FAIL] Failed to get requests: {resp.status_code}")
            return False

        data = resp.json()
        pending = data.get("requests", [])
        print(f"  Found {len(pending)} pending request(s)")

        # Find our request (by robot_name since we just created it)
        our_request = None
        for req in pending:
            if req.get("robot_name") == ROBOT_NAME:
                our_request = req
                break

        if not our_request:
            # If we can't find by name, just take the most recent
            if pending:
                our_request = pending[0]
                print(f"  Using most recent request: {our_request.get('id')}")

        if not our_request:
            print("  [FAIL] No pending requests found")
            return False

        request_id = our_request["id"]
        print(f"  Request ID: {request_id}")

        # Approve the request
        print(f"\n  [4b] Approving pairing request...")
        approve_resp = requests.post(
            f"{PLATFORM_URL}/api/robot-pairing/{request_id}/approve"
        )

        if approve_resp.status_code != 200:
            print(f"  [FAIL] Approval failed: {approve_resp.status_code} - {approve_resp.text}")
            return False

        result = approve_resp.json()
        print(f"  [OK] Approved! Robot ID from API: {result.get('robot_id')}")

        # Wait for credentials via WebSocket
        print("\n  Waiting for credentials via WebSocket...")
        for i in range(10):
            if self.credentials.get("robot_id"):
                break
            await asyncio.sleep(0.5)

        if self.credentials.get("robot_id"):
            print(f"  [OK] Received credentials via WebSocket")
            return True
        else:
            # Credentials might be in API response or need to poll
            # The approve endpoint returns robot_id but not secret via REST
            # Robot should receive via WebSocket pair_status_event
            print("  [WARN] Did not receive credentials via WebSocket")
            print("  Checking if credentials were stored for polling...")

            # Poll get_pairing_status
            await self.sio.emit("get_pairing_status", {
                "cmd_id": str(uuid.uuid4()),
                "username": USER_EMAIL
            }, namespace=NAMESPACE)
            await asyncio.sleep(2)

            if self.credentials.get("robot_id"):
                print(f"  [OK] Got credentials via polling")
                return True
            else:
                print("  [FAIL] Could not retrieve credentials")
                return False

    async def test_authentication(self):
        """Phase 3: Disconnect and reconnect with credentials to test auth."""
        print("\n" + "="*60)
        print("PHASE 3: AUTHENTICATION")
        print("="*60)

        if not self.credentials.get("robot_id") or not self.credentials.get("robot_secret"):
            print("  [SKIP] No credentials available")
            return False

        # Disconnect from pairing session
        print("\n  Disconnecting pairing session...")
        await self.sio.disconnect()
        await asyncio.sleep(1)

        # Create new client for authentication
        print("  Creating new connection for authentication...")
        self.sio = socketio.AsyncClient(logger=False, engineio_logger=False)

        auth_complete = asyncio.Event()

        @self.sio.on("connect", namespace=NAMESPACE)
        async def on_connect():
            print("  [6] Connected for authentication")

        @self.sio.on("authenticate_challenge", namespace=NAMESPACE)
        async def on_challenge(data):
            nonce = data.get("nonce")
            print(f"  [7] Received challenge (nonce={nonce[:16]}...)")

            # Compute HMAC signature
            signature = hmac.new(
                self.credentials["robot_secret"].encode(),
                nonce.encode(),
                hashlib.sha256
            ).hexdigest()

            print(f"  [8] Sending signature...")
            await self.sio.emit("authenticate_response", {
                "signature": signature
            }, namespace=NAMESPACE)

        @self.sio.on("authenticate_result", namespace=NAMESPACE)
        async def on_auth_result(data):
            print(f"  [9] authenticate_result: success={data.get('success')}")
            self.auth_result.update(data)
            auth_complete.set()

        # Connect
        await self.sio.connect(PLATFORM_URL, namespaces=[NAMESPACE], transports=["websocket"])
        await asyncio.sleep(1)

        # Send authenticate_cmd
        print(f"\n  Authenticating as robot {self.credentials['robot_id']}...")
        await self.sio.emit("authenticate_cmd", {
            "robot_id": self.credentials["robot_id"]
        }, namespace=NAMESPACE)

        # Wait for result
        try:
            await asyncio.wait_for(auth_complete.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print("  [FAIL] Authentication timeout")
            return False

        if self.auth_result.get("success"):
            print("  [OK] Authentication successful!")
            return True
        else:
            print(f"  [FAIL] Authentication failed: {self.auth_result.get('message')}")
            return False

    async def cleanup(self):
        """Cleanup connections."""
        if self.sio and self.sio.connected:
            await self.sio.disconnect()


async def main():
    print("="*60)
    print("ROBOT PAIRING & AUTHENTICATION TEST")
    print("="*60)
    print(f"Platform: {PLATFORM_URL}")
    print(f"User: {USER_EMAIL}")
    print(f"Robot: {ROBOT_NAME}")

    test = PairingTest()
    results = {}

    try:
        # Phase 1: Pairing request
        results["pairing_request"] = await test.run_pairing_phase()

        if results["pairing_request"]:
            # Phase 2: User approval
            results["user_approval"] = await test.approve_pairing()

        if results.get("user_approval"):
            # Phase 3: Authentication
            results["authentication"] = await test.test_authentication()

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        await test.cleanup()

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for phase, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {phase}: {status}")

    all_passed = all(results.values()) if results else False
    print()
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
