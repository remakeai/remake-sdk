#!/usr/bin/env python3
"""
Test the SDK's PairingClient.

Usage:
    python test_sdk_pairing.py
"""

import asyncio
import sys
import os
import uuid
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remake_sdk.platform import PairingClient, PairingStatus

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:5000")
USER_EMAIL = "test@example.com"
ROBOT_NAME = f"SDK Test Robot {uuid.uuid4().hex[:6]}"


def approve_request_async(platform_url: str):
    """Background task to approve the pairing request."""
    async def approve():
        await asyncio.sleep(3)  # Wait for request to be created

        # Get pending requests
        resp = requests.get(f"{platform_url}/api/pairing-requests")
        if resp.status_code != 200:
            print(f"  [Auto-approve] Failed to get requests: {resp.status_code}")
            return

        data = resp.json()
        requests_list = data.get("requests", [])

        if not requests_list:
            print("  [Auto-approve] No pending requests found")
            return

        # Approve the most recent
        request_id = requests_list[0]["id"]
        print(f"  [Auto-approve] Approving request {request_id}...")

        approve_resp = requests.post(
            f"{platform_url}/api/robot-pairing/{request_id}/approve"
        )

        if approve_resp.status_code == 200:
            print(f"  [Auto-approve] Success!")
        else:
            print(f"  [Auto-approve] Failed: {approve_resp.text}")

    return approve()


async def main():
    print("="*60)
    print("SDK PAIRING CLIENT TEST")
    print("="*60)
    print(f"Platform: {PLATFORM_URL}")
    print(f"User: {USER_EMAIL}")
    print(f"Robot: {ROBOT_NAME}")
    print()

    def on_status(status: PairingStatus, message: str):
        print(f"  Status: {status.value} - {message}")

    # Start auto-approval in background
    approval_task = asyncio.create_task(approve_request_async(PLATFORM_URL))

    try:
        async with PairingClient(PLATFORM_URL, on_status_change=on_status) as client:
            print("\n[1] Connected to platform")

            print(f"\n[2] Requesting pairing with {USER_EMAIL}...")
            result = await client.request_pairing(
                user_email=USER_EMAIL,
                robot_name=ROBOT_NAME,
                timeout=30
            )

            print(f"\n[3] Result: success={result.success}, status={result.status.value}")

            if result.success:
                print("\n" + "="*60)
                print("PAIRING SUCCESSFUL!")
                print("="*60)
                print(f"  Robot ID:     {result.robot_id}")
                print(f"  Robot Secret: {result.robot_secret[:20]}..." if result.robot_secret else "  No secret")

                creds = result.credentials
                if creds:
                    print(f"\n  Credentials object: {creds}")
            else:
                print(f"\n  Error: {result.error}")
                print(f"  Message: {result.message}")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        approval_task.cancel()
        try:
            await approval_task
        except asyncio.CancelledError:
            pass

    return result.success


if __name__ == "__main__":
    success = asyncio.run(main())
    print()
    sys.exit(0 if success else 1)
