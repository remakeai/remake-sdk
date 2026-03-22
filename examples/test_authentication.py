#!/usr/bin/env python3
"""
Test robot authentication using the SDK's PlatformClient.

Tests the challenge-response authentication flow:
1. Robot connects to platform
2. Sends authenticate_cmd with robot_id
3. Receives challenge (nonce)
4. Computes HMAC-SHA256(nonce, secret) and sends signature
5. Receives authenticate_result (success/failure)

Usage:
    # With pre-provisioned test robot
    python test_authentication.py

    # With custom credentials
    ROBOT_ID=xxx ROBOT_SECRET=yyy python test_authentication.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remake_sdk.platform import PlatformClient, PlatformConfig, ConnectionState
from remake_sdk.common.types import AppCommand

PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:5000")
ROBOT_ID = os.environ.get("ROBOT_ID", "test-robot-v2-001")
ROBOT_SECRET = os.environ.get("ROBOT_SECRET", "test-secret-v2-001")


async def main():
    print("="*60)
    print("ROBOT AUTHENTICATION TEST")
    print("="*60)
    print(f"Platform:     {PLATFORM_URL}")
    print(f"Robot ID:     {ROBOT_ID}")
    print(f"Robot Secret: {ROBOT_SECRET[:10]}...")
    print()

    # Track state changes
    states = []

    config = PlatformConfig(
        platform_url=PLATFORM_URL,
        robot_id=ROBOT_ID,
        robot_secret=ROBOT_SECRET,
        reconnect=False
    )

    client = PlatformClient(config)

    @client.on_state_change
    def on_state(state: ConnectionState):
        states.append(state)
        print(f"  State: {state.value}")

    @client.on_app_command
    def on_command(cmd: AppCommand):
        print(f"  Command received: {cmd.action} {cmd.app_id}")

    print("Step 1: Connecting...")
    try:
        success = await client.connect(timeout=10.0)
    except Exception as e:
        print(f"\n  ERROR: {e}")
        return False

    if not success:
        print("\n  FAILED: Authentication unsuccessful")
        return False

    print(f"\n  SUCCESS: Authenticated as {ROBOT_ID}")

    # Verify state progression
    print("\nStep 2: Verifying state progression...")
    expected_states = [
        ConnectionState.CONNECTING,
        ConnectionState.CONNECTED,
        ConnectionState.AUTHENTICATING,
        ConnectionState.AUTHENTICATED
    ]

    state_check = all(s in states for s in expected_states)
    if state_check:
        print("  State progression: PASS")
    else:
        print(f"  State progression: FAIL (got {[s.value for s in states]})")

    # Test invalid authentication
    print("\nStep 3: Testing invalid credentials...")
    await client.disconnect()
    await asyncio.sleep(1)

    bad_config = PlatformConfig(
        platform_url=PLATFORM_URL,
        robot_id=ROBOT_ID,
        robot_secret="wrong-secret",
        reconnect=False
    )

    bad_client = PlatformClient(bad_config)

    try:
        bad_success = await bad_client.connect(timeout=10.0)
        if not bad_success:
            print("  Invalid credentials rejected: PASS")
        else:
            print("  Invalid credentials rejected: FAIL (was accepted!)")
    except Exception as e:
        print(f"  Invalid credentials rejected: PASS ({type(e).__name__})")
    finally:
        await bad_client.disconnect()

    # Summary
    print("\n" + "="*60)
    print("AUTHENTICATION TEST COMPLETE")
    print("="*60)

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
