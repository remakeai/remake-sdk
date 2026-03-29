"""
Entry point for: python -m remake_agent
"""

import argparse
from pathlib import Path

from .config import AgentConfig
from .server import run_agent


def main():
    parser = argparse.ArgumentParser(description="Remake Host Agent")
    parser.add_argument("--host", default=None, help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: 8785)")
    parser.add_argument("--config", default=None, help="Config file path")
    parser.add_argument("--runtime", choices=["docker", "podman"], default=None,
                        help="Container runtime (default: docker)")
    parser.add_argument("--network", default=None, help="Docker network name")
    parser.add_argument("--data-root", default=None, help="Data storage root directory")
    args = parser.parse_args()

    # Load config from file
    config_path = Path(args.config) if args.config else None
    config = AgentConfig.load(config_path)

    # CLI args override config file
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.runtime:
        config.container_runtime = args.runtime
    if args.network:
        config.network = args.network
    if args.data_root:
        config.data_root = args.data_root

    run_agent(config)


if __name__ == "__main__":
    main()
