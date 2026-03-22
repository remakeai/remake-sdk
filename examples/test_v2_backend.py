#!/usr/bin/env python3
"""
Test script for v2 backend integration.

Prerequisites:
1. Backend running: cd ~/appstore/backend && node server-refactored.js
2. A robot registered in the database with known credentials

Usage:
    python test_v2_backend.py
"""

import asyncio
import os
import sys

# Add parent directory to path for local development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remake_sdk.platform import PlatformConfig, PlatformClient
from remake_sdk.common.types import AppCommand


async def main():
    # Configuration - update these for your test robot
    config = PlatformConfig(
        platform_url="http://localhost:5000",
        robot_id=os.environ.get("ROBOT_ID", "test-robot-001"),
        robot_secret=os.environ.get("ROBOT_SECRET", "test-secret-001"),
        reconnect=False  # Don't reconnect for testing
    )

    print(f"Connecting to {config.platform_url} as robot {config.robot_id}...")

    client = PlatformClient(config)

    # Track received commands
    received_commands = []

    @client.on_app_command
    def handle_app_command(cmd: AppCommand):
        print(f"\n{'='*50}")
        print(f"RECEIVED APP COMMAND:")
        print(f"  Action: {cmd.action}")
        print(f"  App ID: {cmd.app_id}")
        print(f"  Cmd ID: {cmd.cmd_id}")
        if cmd.container_image:
            print(f"  Container: {cmd.container_image}")
        if cmd.entitlements:
            print(f"  Entitlements: {cmd.entitlements}")
        print(f"{'='*50}\n")
        received_commands.append(cmd)

        # Send response back (schedule async emit)
        async def send_response():
            if cmd.action == "launch":
                print("Sending launch_app_response (success)...")
                await client._sio.emit("launch_app_response", {
                    "cmd_id": cmd.cmd_id,
                    "success": True,
                    "error_code": None,
                    "error_message": None
                }, namespace="/robot-control")
            elif cmd.action == "stop":
                print("Sending stop_app_response (success)...")
                await client._sio.emit("stop_app_response", {
                    "cmd_id": cmd.cmd_id,
                    "success": True
                }, namespace="/robot-control")

        asyncio.create_task(send_response())

    @client.on_state_change
    def handle_state(state):
        print(f"Connection state: {state}")

    # Connect
    try:
        connected = await client.connect(timeout=10.0)
        if not connected:
            print("Failed to connect!")
            return

        print("\nConnected and authenticated!")
        print("\nWaiting for commands...")
        print("To test, run in another terminal:")
        print(f'  curl -X POST http://localhost:5000/api/v2/robots/{config.robot_id}/apps/test-app/launch \\')
        print('    -H "Authorization: Bearer <your-jwt-token>" \\')
        print('    -H "Content-Type: application/json"')
        print("\nPress Ctrl+C to exit.\n")

        # Keep running
        await client.run()

    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print(f"\nReceived {len(received_commands)} command(s) during session.")


if __name__ == "__main__":
    asyncio.run(main())
