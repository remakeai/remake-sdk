"""
Container backends for app management.

Provides a common interface for managing app containers, with
implementations for local Podman and remote Host Agent.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Tuple

from ..app_manager import ContainerStatus


class ContainerBackend(ABC):
    """
    Abstract interface for container lifecycle management.

    Implementations:
    - PodmanBackend: Local Podman subprocess calls
    - HostAgentBackend: HTTP calls to the Host Agent
    """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is available and working."""
        ...

    @abstractmethod
    def pull(self, image: str) -> Tuple[bool, Optional[str]]:
        """
        Pull a container image.

        Returns:
            Tuple of (success, error_message)
        """
        ...

    @abstractmethod
    def image_exists(self, image: str) -> bool:
        """Check if a container image exists locally."""
        ...

    @abstractmethod
    def remove_image(self, image: str) -> bool:
        """Remove a container image."""
        ...

    @abstractmethod
    def run(
        self,
        app_id: str,
        image: str,
        ports: Optional[List[dict]] = None,
        environment: Optional[dict] = None,
        volumes: Optional[List[dict]] = None,
        network: Optional[str] = None,
        resources: Optional[dict] = None,
        labels: Optional[dict] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Create and start an app container.

        Args:
            app_id: App identifier (used as container name)
            image: Container image
            ports: Port mappings [{"host": 8080, "container": 8080}]
            environment: Environment variables
            volumes: Volume mounts [{"host": "/path", "container": "/path", "mode": "rw"}]
            network: Network name or mode
            resources: Resource limits {"memory": "256m", "cpus": "1.0"}
            labels: Container labels

        Returns:
            Tuple of (success, container_id_or_error, message)
        """
        ...

    @abstractmethod
    def stop(self, app_id: str, force: bool = False) -> Tuple[bool, str]:
        """
        Stop a running container.

        Returns:
            Tuple of (success, message)
        """
        ...

    @abstractmethod
    def status(self, app_id: str) -> Optional[ContainerStatus]:
        """Get status of a container by app_id."""
        ...

    @abstractmethod
    def list_running(self) -> List[ContainerStatus]:
        """List all running app containers."""
        ...

    @abstractmethod
    def logs(self, app_id: str, tail: int = 100) -> Optional[str]:
        """Get container logs."""
        ...
