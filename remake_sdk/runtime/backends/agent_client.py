"""
Host Agent container backend.

Manages app containers by sending HTTP requests to the Host Agent
running on the host machine.
"""

import logging
from typing import Optional, List, Tuple

import requests

from . import ContainerBackend
from ..app_manager import ContainerStatus

logger = logging.getLogger(__name__)

DEFAULT_AGENT_URL = "http://host.docker.internal:8785"


class HostAgentBackend(ContainerBackend):
    """Container backend using the Host Agent REST API."""

    def __init__(self, agent_url: str = DEFAULT_AGENT_URL):
        self.agent_url = agent_url.rstrip("/")
        self._timeout = 10.0
        self._pull_timeout = 300.0

    def _url(self, path: str) -> str:
        return f"{self.agent_url}{path}"

    def _get(self, path: str, timeout: float = None) -> Optional[dict]:
        try:
            resp = requests.get(
                self._url(path),
                timeout=timeout or self._timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"Agent GET {path} failed: {e}")
            return None

    def _post(self, path: str, data: dict = None, timeout: float = None) -> Optional[dict]:
        try:
            resp = requests.post(
                self._url(path),
                json=data or {},
                timeout=timeout or self._timeout
            )
            return resp.json()
        except Exception as e:
            logger.debug(f"Agent POST {path} failed: {e}")
            return None

    def _delete(self, path: str) -> Optional[dict]:
        try:
            resp = requests.delete(
                self._url(path),
                timeout=self._timeout
            )
            return resp.json()
        except Exception as e:
            logger.debug(f"Agent DELETE {path} failed: {e}")
            return None

    def is_available(self) -> bool:
        try:
            resp = requests.get(self._url("/health"), timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def pull(self, image: str) -> Tuple[bool, Optional[str]]:
        logger.info(f"Pulling image {image} via Host Agent...")
        result = self._post(
            "/containers/pull",
            {"image": image},
            timeout=self._pull_timeout
        )
        if result is None:
            return False, "Host Agent unreachable"
        if result.get("success"):
            return True, None
        return False, result.get("error", "Pull failed")

    def image_exists(self, image: str) -> bool:
        result = self._get(f"/images/{requests.utils.quote(image, safe='')}")
        return result is not None and result.get("exists", False)

    def remove_image(self, image: str) -> bool:
        result = self._delete(f"/images/{requests.utils.quote(image, safe='')}")
        return result is not None and result.get("success", False)

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
        config = {
            "app_id": app_id,
            "image": image,
        }
        if ports:
            config["ports"] = ports
        if environment:
            config["environment"] = environment
        if volumes:
            config["volumes"] = volumes
        if network:
            config["network"] = network
        if resources:
            config["resources"] = resources
        if labels:
            config["labels"] = labels

        # Ensure remake labels are always set
        config.setdefault("labels", {})
        config["labels"]["remake.app_id"] = app_id
        config["labels"]["remake.managed"] = "true"

        result = self._post("/containers/create", config, timeout=30.0)
        if result is None:
            return False, "agent_unreachable", "Host Agent is not reachable"
        if result.get("success"):
            container_id = result.get("container_id", "unknown")
            return True, container_id, "App launched successfully"
        return False, result.get("error", "launch_failed"), result.get("message", "Launch failed")

    def stop(self, app_id: str, force: bool = False) -> Tuple[bool, str]:
        result = self._post(
            f"/containers/{app_id}/stop",
            {"force": force}
        )
        if result is None:
            return False, "Host Agent is not reachable"
        if result.get("success"):
            return True, result.get("message", "App stopped")
        return False, result.get("message", "Stop failed")

    def status(self, app_id: str) -> Optional[ContainerStatus]:
        result = self._get(f"/containers/{app_id}")
        if result is None or not result.get("success"):
            return None
        c = result.get("container", {})
        return ContainerStatus(
            app_id=c.get("app_id", app_id),
            container_id=c.get("container_id", ""),
            status=c.get("status", "unknown"),
            image=c.get("image", ""),
            started_at=c.get("started_at"),
        )

    def list_running(self) -> List[ContainerStatus]:
        result = self._get("/containers")
        if result is None or not result.get("success"):
            return []
        containers = []
        for c in result.get("containers", []):
            containers.append(ContainerStatus(
                app_id=c.get("app_id", c.get("name", "")),
                container_id=c.get("container_id", ""),
                status=c.get("status", ""),
                image=c.get("image", ""),
                started_at=c.get("started_at"),
            ))
        return containers

    def logs(self, app_id: str, tail: int = 100) -> Optional[str]:
        result = self._get(f"/containers/{app_id}/logs?tail={tail}")
        if result is None:
            return None
        return result.get("logs")
