"""Tests for platform configuration module."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from remake_sdk.platform.config import (
    PlatformConfig,
    load_config,
    save_config,
    load_credentials,
    save_credentials,
    get_robot_credentials,
    set_robot_credentials,
    clear_credentials,
    _default_config,
)


@pytest.fixture
def temp_config_dir(tmp_path, monkeypatch):
    """Create a temporary config directory."""
    config_dir = tmp_path / ".config" / "remake"
    config_dir.mkdir(parents=True)

    # Patch the module constants
    import remake_sdk.platform.config as config_module
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_dir / "config.yml")
    monkeypatch.setattr(config_module, "CREDENTIALS_FILE", config_dir / "credentials.yml")

    return config_dir


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, temp_config_dir):
        """Should return defaults when config file doesn't exist."""
        config = load_config()

        assert "platform" in config
        assert config["platform"]["url"] == "https://api.remake.ai"
        assert "runtime" in config
        assert "simulation" in config

    def test_loads_existing_config(self, temp_config_dir):
        """Should load config from file."""
        config_file = temp_config_dir / "config.yml"
        config_file.write_text(yaml.dump({
            "platform": {"url": "https://custom.api.com"},
            "runtime": {"mode": "dev"},
        }))

        config = load_config()

        assert config["platform"]["url"] == "https://custom.api.com"
        assert config["runtime"]["mode"] == "dev"

    def test_merges_with_defaults(self, temp_config_dir):
        """Should merge partial config with defaults."""
        config_file = temp_config_dir / "config.yml"
        config_file.write_text(yaml.dump({
            "platform": {"url": "https://custom.api.com"},
            # Missing runtime and simulation
        }))

        config = load_config()

        assert config["platform"]["url"] == "https://custom.api.com"
        assert "runtime" in config  # Default added
        assert config["runtime"]["mode"] == "prod"


class TestSaveConfig:
    def test_saves_config(self, temp_config_dir):
        """Should save config to file."""
        config = {"platform": {"url": "https://test.api.com"}}
        save_config(config)

        config_file = temp_config_dir / "config.yml"
        assert config_file.exists()

        loaded = yaml.safe_load(config_file.read_text())
        assert loaded["platform"]["url"] == "https://test.api.com"

    def test_creates_directory(self, tmp_path, monkeypatch):
        """Should create config directory if it doesn't exist."""
        import remake_sdk.platform.config as config_module

        new_dir = tmp_path / "new" / "nested" / "dir"
        monkeypatch.setattr(config_module, "CONFIG_DIR", new_dir)
        monkeypatch.setattr(config_module, "CONFIG_FILE", new_dir / "config.yml")

        save_config({"test": "value"})

        assert new_dir.exists()
        assert (new_dir / "config.yml").exists()


class TestCredentials:
    def test_save_and_load_credentials(self, temp_config_dir):
        """Should save and load credentials."""
        save_credentials({
            "robot_id": "robot-123",
            "robot_secret": "secret-456",
        })

        creds = load_credentials()

        assert creds["robot_id"] == "robot-123"
        assert creds["robot_secret"] == "secret-456"

    def test_set_robot_credentials(self, temp_config_dir):
        """Should set robot credentials with helper function."""
        set_robot_credentials(
            robot_id="robot-abc",
            robot_secret="secret-xyz",
            device_id="device-001",
            robot_name="Test Robot",
        )

        robot_id, robot_secret = get_robot_credentials()

        assert robot_id == "robot-abc"
        assert robot_secret == "secret-xyz"

    def test_clear_credentials(self, temp_config_dir):
        """Should clear credentials."""
        set_robot_credentials("robot-123", "secret-456")
        clear_credentials()

        robot_id, robot_secret = get_robot_credentials()

        assert robot_id is None
        assert robot_secret is None


class TestPlatformConfig:
    def test_from_file(self, temp_config_dir):
        """Should load PlatformConfig from files."""
        # Save config
        save_config({
            "platform": {"url": "https://test.api.com"},
            "runtime": {"mode": "dev"},
        })

        # Save credentials
        save_credentials({
            "robot_id": "robot-test",
            "robot_secret": "secret-test",
        })

        config = PlatformConfig.from_file()

        assert config.platform_url == "https://test.api.com"
        assert config.robot_id == "robot-test"
        assert config.robot_secret == "secret-test"
        assert config.runtime_mode == "dev"

    def test_defaults(self):
        """Should have sensible defaults."""
        config = PlatformConfig()

        assert config.platform_url == "https://api.remake.ai"
        assert config.reconnect is True
        assert config.heartbeat_interval == 30.0
