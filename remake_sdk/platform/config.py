"""
Configuration management for Remake SDK.

Handles:
- Platform connection settings
- Robot credentials (stored securely with chmod 600)
- Runtime configuration

Config file location: ~/.config/remake/config.yml
Credentials file: ~/.config/remake/credentials.yml (chmod 600)
"""

import os
import sys
import stat
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, field


DEFAULT_PLATFORM_URL = "https://api.remake.ai"
DEFAULT_PLATFORM_FRONTEND_URL = "https://remake.ai"

CONFIG_DIR = Path.home() / ".config" / "remake"
CONFIG_FILE = CONFIG_DIR / "config.yml"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.yml"


@dataclass
class PlatformConfig:
    """Configuration for platform connection."""
    platform_url: str = DEFAULT_PLATFORM_URL
    robot_id: Optional[str] = None
    robot_secret: Optional[str] = None

    # Connection settings
    reconnect: bool = True
    reconnect_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    heartbeat_interval: float = 30.0

    # Runtime settings
    runtime_mode: str = "prod"  # "prod", "dev", "mock"
    socket_path: str = "/var/run/remake/robot.sock"

    @classmethod
    def from_file(cls, config_path: Optional[Path] = None) -> "PlatformConfig":
        """Load configuration from file."""
        config = load_config(config_path)
        creds = load_credentials()

        return cls(
            platform_url=config.get("platform", {}).get("url", DEFAULT_PLATFORM_URL),
            robot_id=creds.get("robot_id"),
            robot_secret=creds.get("robot_secret"),
            reconnect=config.get("platform", {}).get("reconnect", True),
            reconnect_delay=config.get("platform", {}).get("reconnect_delay", 1.0),
            reconnect_max_delay=config.get("platform", {}).get("reconnect_max_delay", 30.0),
            heartbeat_interval=config.get("platform", {}).get("heartbeat_interval", 30.0),
            runtime_mode=config.get("runtime", {}).get("mode", "prod"),
            socket_path=config.get("runtime", {}).get("socket_path", "/var/run/remake/robot.sock"),
        )


def _default_config() -> Dict[str, Any]:
    """Return default configuration."""
    return {
        "platform": {
            "url": DEFAULT_PLATFORM_URL,
            "reconnect": True,
            "reconnect_delay": 1.0,
            "reconnect_max_delay": 30.0,
            "heartbeat_interval": 30.0,
        },
        "runtime": {
            "mode": "prod",
            "socket_path": "/var/run/remake/robot.sock",
            "dashboard_port": 8080,
        },
        "simulation": {
            "default_simulator": "unity",
            "unity_bridge_port": 9090,
        },
    }


def _default_credentials() -> Dict[str, Any]:
    """Return default credentials structure."""
    return {
        "robot_id": None,
        "robot_secret": None,
        "registry_token": None,
    }


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    return CONFIG_DIR


def get_config_path() -> Path:
    """Get the config file path."""
    return CONFIG_FILE


def get_credentials_path() -> Path:
    """Get the credentials file path."""
    return CREDENTIALS_FILE


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration from file.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Configuration dictionary with defaults for missing keys.
    """
    path = config_path or CONFIG_FILE

    if not path.exists():
        return _default_config()

    try:
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        print(f"Warning: Config file error ({e}), using defaults")
        return _default_config()

    if not isinstance(config, dict):
        return _default_config()

    # Merge with defaults to ensure all keys exist
    defaults = _default_config()
    for key, value in defaults.items():
        if key not in config:
            config[key] = value
        elif isinstance(value, dict):
            for subkey, subvalue in value.items():
                if subkey not in config[key]:
                    config[key][subkey] = subvalue

    return config


def save_config(config: Dict[str, Any], config_path: Optional[Path] = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration dictionary to save.
        config_path: Optional path to config file. Uses default if not provided.
    """
    path = config_path or CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def load_credentials() -> Dict[str, Any]:
    """
    Load credentials from secure file.

    Returns:
        Credentials dictionary.
    """
    if not CREDENTIALS_FILE.exists():
        return _default_credentials()

    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            creds = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return _default_credentials()

    if not isinstance(creds, dict):
        return _default_credentials()

    return creds


def save_credentials(creds: Dict[str, Any]) -> None:
    """
    Save credentials to secure file (chmod 600 on Unix).

    Args:
        creds: Credentials dictionary to save.
    """
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(CREDENTIALS_FILE, 'w') as f:
        yaml.dump(creds, f, default_flow_style=False, sort_keys=False)

    # Set secure permissions (Unix only)
    if sys.platform != 'win32':
        os.chmod(CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)


def get_platform_url() -> str:
    """Get the platform API URL."""
    config = load_config()
    return config.get("platform", {}).get("url", DEFAULT_PLATFORM_URL)


def get_platform_frontend_url() -> str:
    """Get the platform frontend URL (for browser instructions)."""
    config = load_config()
    frontend = config.get("platform", {}).get("frontend_url")
    if frontend:
        return frontend

    # Derive from API URL
    api_url = get_platform_url()
    if "://api." in api_url:
        return api_url.replace("://api.", "://", 1)
    if "localhost:5000" in api_url:
        return api_url.replace(":5000", ":3000")

    return DEFAULT_PLATFORM_FRONTEND_URL


def set_platform_url(url: str, frontend_url: Optional[str] = None) -> None:
    """Set the platform URL."""
    config = load_config()
    config["platform"]["url"] = url
    if frontend_url:
        config["platform"]["frontend_url"] = frontend_url
    save_config(config)


def get_robot_credentials() -> tuple[Optional[str], Optional[str]]:
    """
    Get robot credentials.

    Returns:
        Tuple of (robot_id, robot_secret), either may be None.
    """
    creds = load_credentials()
    return creds.get("robot_id"), creds.get("robot_secret")


def set_robot_credentials(
    robot_id: str,
    robot_secret: str,
    device_id: Optional[str] = None,
    product_id: Optional[str] = None,
    robot_name: Optional[str] = None,
) -> None:
    """
    Store robot credentials securely.

    Args:
        robot_id: Robot identifier from platform.
        robot_secret: Robot secret for authentication.
        device_id: Optional device identifier.
        product_id: Optional product identifier.
        robot_name: Optional robot name.
    """
    creds = load_credentials()
    creds["robot_id"] = robot_id
    creds["robot_secret"] = robot_secret
    creds["device_id"] = device_id
    creds["product_id"] = product_id
    creds["robot_name"] = robot_name
    creds["paired_at"] = datetime.now(timezone.utc).isoformat()
    save_credentials(creds)


def clear_credentials() -> None:
    """Clear all stored credentials."""
    save_credentials(_default_credentials())


def get_runtime_mode() -> str:
    """Get the runtime mode (prod, dev, mock)."""
    config = load_config()
    return config.get("runtime", {}).get("mode", "prod")


def set_runtime_mode(mode: str) -> None:
    """Set the runtime mode."""
    if mode not in ("prod", "dev", "mock"):
        raise ValueError(f"Invalid runtime mode: {mode}")
    config = load_config()
    config["runtime"]["mode"] = mode
    save_config(config)
