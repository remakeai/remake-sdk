"""
Host Agent configuration.

Loads from ~/.remake/agent.yml with sensible defaults.
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


DEFAULT_CONFIG_PATH = Path.home() / ".remake" / "agent.yml"


@dataclass
class AgentConfig:
    """Host Agent configuration."""
    host: str = "0.0.0.0"
    port: int = 8785
    network: str = "remake-net"
    robot_container: str = "remake-robot"
    data_root: str = str(Path.home() / ".remake")
    default_memory: str = "256m"
    default_cpus: str = "1.0"
    container_runtime: str = "docker"  # "docker" or "podman"

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "AgentConfig":
        """Load config from YAML file, falling back to defaults."""
        path = config_path or DEFAULT_CONFIG_PATH

        if not path.exists():
            return cls()

        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return cls()

        agent = data.get("agent", {})
        storage = data.get("storage", {})
        defaults = data.get("defaults", {})

        return cls(
            host=agent.get("host", "0.0.0.0"),
            port=agent.get("port", 8785),
            network=agent.get("network", "remake-net"),
            robot_container=agent.get("robot_container", "remake-robot"),
            data_root=storage.get("data_root", str(Path.home() / ".remake")),
            default_memory=defaults.get("memory", "256m"),
            default_cpus=defaults.get("cpus", "1.0"),
            container_runtime=data.get("container_runtime", "docker"),
        )
