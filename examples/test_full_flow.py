#!/usr/bin/env python3
"""
Test full flow: Pairing → Save credentials → Authenticate → Receive commands

Usage:
    python test_full_flow.py
"""

import asyncio
import sys
import os
import uuid
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remake_sdk.platform import (
    PairingClient,
    PlatformClient,
    PlatformConfig,
    PairingStatus,
)
from remake_sdk.common.types import AppCommand

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:5000")
USER_EMAIL = "test@example.com"
ROBOT_NAME = f"Full Flow Test {uuid.uuid4().hex[:4]}"


async def auto_approve(platform_url: str):
    """Background task to approve pairing requests."""
    await asyncio.sleep(2)
    resp = requests.get(f"{platform_url}/api/pairing-requests")
    if resp.status_code == 200:
        data = resp.json()
        if data.get("requests"):
            req_id = data["requests"][0]["id"]
            requests.post(f"{platform_url}/api/robot-pairing/{req_id}/approve")
            print("  [Auto-approve] Done")


async def main():
    print("="*60)
    print("FULL FLOW TEST: Pairing → Auth → Commands")
    print("="*60)
    print()

    # ================================================================
    # Phase 1: Pairing
    # ================================================================
    print("PHASE 1: PAIRING")
    print("-"*40)

    approval_task = asyncio.create_task(auto_approve(PLATFORM_URL))

    try:
        async with PairingClient(PLATFORM_URL) as pairing:
            result = await pairing.request_pairing(
                user_email=USER_EMAIL,
                robot_name=ROBOT_NAME,
                timeout=15
            )

            if not result.success:
                print(f"  FAILED: {result.error}")
                return False

            print(f"  Robot ID: {result.robot_id}")
            print(f"  Got credentials!")

            credentials = result.credentials

    finally:
        approval_task.cancel()
        try:
            await approval_task
        except asyncio.CancelledError:
            pass

    # ================================================================
    # Phase 2: Authentication
    # ================================================================
    print()
    print("PHASE 2: AUTHENTICATION")
    print("-"*40)

    config = PlatformConfig(
        platform_url=PLATFORM_URL,
        robot_id=credentials.robot_id,
        robot_secret=credentials.robot_secret,
        reconnect=False
    )

    client = PlatformClient(config)
    commands_received = []

    @client.on_app_command
    def handle_command(cmd: AppCommand):
        print(f"  Received command: {cmd.action} {cmd.app_id}")
        commands_received.append(cmd)

    connected = await client.connect(timeout=10)
    if not connected:
        print("  FAILED: Could not connect")
        return False

    print(f"  Authenticated as {credentials.robot_id}")

    # ================================================================
    # Phase 3: Receive Command
    # ================================================================
    print()
    print("PHASE 3: RECEIVE COMMAND")
    print("-"*40)

    # Send a test launch command via REST API
    print("  Sending launch command via REST API...")

    # First, ensure there's a test app
    resp = requests.post(
        f"{PLATFORM_URL}/api/v2/robots/{credentials.robot_id}/apps/com.test.app/launch"
    )

    if resp.status_code == 200:
        print(f"  API response: {resp.json()}")
    else:
        print(f"  API error: {resp.status_code} (app may not be installed)")

    # Wait briefly for command
    await asyncio.sleep(2)

    await client.disconnect()

    # ================================================================
    # Summary
    # ================================================================
    print()
    print("="*60)
    print("SUMMARY")
    print("="*60)
    print(f"  Pairing:        PASS")
    print(f"  Authentication: PASS")
    print(f"  Commands:       {len(commands_received)} received")

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    print()
    sys.exit(0 if success else 1)
