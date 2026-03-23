#!/usr/bin/env python3
"""
Hello World App - A simple app for testing the Remake runtime.

This app demonstrates:
1. Basic app startup
2. Periodic logging
3. Graceful shutdown
"""

import signal
import sys
import time
import os

# App metadata
APP_ID = "com.example.hello-world"
VERSION = "1.0.0"


def main():
    print(f"Hello World App v{VERSION}")
    print(f"App ID: {APP_ID}")
    print(f"PID: {os.getpid()}")
    print()

    # Set up graceful shutdown
    running = True

    def handle_signal(signum, frame):
        nonlocal running
        print(f"\nReceived signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print("App started! Running until stopped...")
    print("-" * 40)

    counter = 0
    while running:
        counter += 1
        print(f"[{counter}] Hello from the container! Time: {time.strftime('%H:%M:%S')}")

        # Sleep in small increments to respond to signals quickly
        for _ in range(10):
            if not running:
                break
            time.sleep(1)

    print("-" * 40)
    print("Goodbye! App stopped cleanly.")
    sys.exit(0)


if __name__ == "__main__":
    main()
