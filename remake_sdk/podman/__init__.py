"""
Podman SDK - Container management.

This module handles app container lifecycle:
- Launching app containers
- Stopping containers
- Image management
- Volume/mount setup

Example:
    from remake_sdk.podman import ContainerManager, AppConfig

    manager = ContainerManager()

    config = AppConfig(
        app_id="com.example.app",
        image="registry.remake.ai/apps/example:1.0",
        entitlements=["movement", "camera"],
    )

    container = await manager.launch(config)
    await manager.stop(config.app_id)
"""

# TODO: Implement in Phase 2
# from .manager import ContainerManager, AppConfig

__all__ = []
