"""
Runtime REST API - HTTP interface for CLI and local tools.

Provides endpoints for:
- App installation/uninstallation
- App lifecycle (launch/stop)
- Status queries
"""

import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional, Callable, Any
import threading

logger = logging.getLogger(__name__)


class RuntimeAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for runtime API."""

    # Reference to AppManager set by RuntimeAPI
    app_manager = None
    app_registry = None

    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.debug(f"API: {args[0]}")

    def _send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[dict]:
        """Read JSON request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            body = self.rfile.read(content_length)
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self._send_json({"status": "healthy"})

        elif path == "/status":
            self._handle_status()

        elif path == "/apps":
            self._handle_list_apps()

        elif path == "/apps/running":
            self._handle_list_running()

        elif path.startswith("/apps/") and path.count("/") == 2:
            app_id = path.split("/")[2]
            self._handle_get_app(app_id)

        else:
            self._send_json({"error": "not_found"}, 404)

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/apps/install":
            self._handle_install()

        elif path.startswith("/apps/") and path.endswith("/launch"):
            app_id = path.split("/")[2]
            self._handle_launch(app_id)

        elif path.startswith("/apps/") and path.endswith("/stop"):
            app_id = path.split("/")[2]
            self._handle_stop(app_id)

        else:
            self._send_json({"error": "not_found"}, 404)

    def do_DELETE(self):
        """Handle DELETE requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/apps/") and path.count("/") == 2:
            app_id = path.split("/")[2]
            self._handle_uninstall(app_id)

        else:
            self._send_json({"error": "not_found"}, 404)

    def _handle_status(self):
        """GET /status - Runtime status."""
        running = self.app_manager.list_running() if self.app_manager else []
        installed = self.app_registry.list_all() if self.app_registry else []

        self._send_json({
            "status": "running",
            "apps": {
                "installed": len(installed),
                "running": len(running)
            }
        })

    def _handle_list_apps(self):
        """GET /apps - List installed apps."""
        if not self.app_registry:
            self._send_json({"error": "registry_unavailable"}, 500)
            return

        apps = self.app_registry.list_all()
        self._send_json({
            "success": True,
            "apps": [app.to_dict() for app in apps]
        })

    def _handle_list_running(self):
        """GET /apps/running - List running apps."""
        if not self.app_manager:
            self._send_json({"error": "manager_unavailable"}, 500)
            return

        running = self.app_manager.list_running()
        self._send_json({
            "success": True,
            "apps": [
                {
                    "app_id": c.app_id,
                    "container_id": c.container_id,
                    "status": c.status,
                    "image": c.image,
                    "started_at": c.started_at
                }
                for c in running
            ]
        })

    def _handle_get_app(self, app_id: str):
        """GET /apps/{app_id} - Get app details."""
        if not self.app_registry:
            self._send_json({"error": "registry_unavailable"}, 500)
            return

        app = self.app_registry.get(app_id)
        if not app:
            self._send_json({"error": "not_found", "message": f"App {app_id} not found"}, 404)
            return

        # Add runtime status
        status = self.app_manager.status(app_id) if self.app_manager else None

        data = app.to_dict()
        data["running"] = status is not None and status.status == "running"
        if status:
            data["container_id"] = status.container_id
            data["started_at"] = status.started_at

        self._send_json({"success": True, "app": data})

    def _handle_install(self):
        """POST /apps/install - Install an app."""
        if not self.app_manager:
            self._send_json({"error": "manager_unavailable"}, 500)
            return

        body = self._read_json()
        if body is None:
            self._send_json({"error": "invalid_json"}, 400)
            return

        app_id = body.get("app_id")
        if not app_id:
            self._send_json({"error": "missing_app_id"}, 400)
            return

        result = self.app_manager.install(
            app_id=app_id,
            version=body.get("version", "latest"),
            container_image=body.get("container_image"),
            name=body.get("name"),
            description=body.get("description"),
            entitlements=body.get("entitlements"),
            source=body.get("source", "local")
        )

        status = 200 if result.success else 500
        self._send_json({
            "success": result.success,
            "app_id": result.app_id,
            "version": result.version,
            "container_image": result.container_image,
            "error": result.error,
            "message": result.message
        }, status)

    def _handle_uninstall(self, app_id: str):
        """DELETE /apps/{app_id} - Uninstall an app."""
        if not self.app_manager:
            self._send_json({"error": "manager_unavailable"}, 500)
            return

        result = self.app_manager.uninstall(app_id)

        status = 200 if result.success else 404
        self._send_json({
            "success": result.success,
            "app_id": result.app_id,
            "error": result.error,
            "message": result.message
        }, status)

    def _handle_launch(self, app_id: str):
        """POST /apps/{app_id}/launch - Launch an app."""
        if not self.app_manager:
            self._send_json({"error": "manager_unavailable"}, 500)
            return

        body = self._read_json() or {}

        success, result, message = self.app_manager.launch(
            app_id=app_id,
            container_image=body.get("container_image"),
            entitlements=body.get("entitlements")
        )

        status = 200 if success else 500
        self._send_json({
            "success": success,
            "app_id": app_id,
            "container_id": result if success else None,
            "error": result if not success else None,
            "message": message
        }, status)

    def _handle_stop(self, app_id: str):
        """POST /apps/{app_id}/stop - Stop an app."""
        if not self.app_manager:
            self._send_json({"error": "manager_unavailable"}, 500)
            return

        body = self._read_json() or {}
        force = body.get("force", False)

        success, message = self.app_manager.stop(app_id, force=force)

        self._send_json({
            "success": success,
            "app_id": app_id,
            "message": message
        })


class RuntimeAPI:
    """
    Runtime REST API server.

    Provides HTTP interface for CLI and local tools to interact
    with the runtime.
    """

    def __init__(
        self,
        app_manager,
        app_registry,
        host: str = "127.0.0.1",
        port: int = 8787
    ):
        self.app_manager = app_manager
        self.app_registry = app_registry
        self.host = host
        self.port = port
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the API server in a background thread."""
        # Set references on handler class
        RuntimeAPIHandler.app_manager = self.app_manager
        RuntimeAPIHandler.app_registry = self.app_registry

        self.server = HTTPServer((self.host, self.port), RuntimeAPIHandler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Runtime API started on http://{self.host}:{self.port}")

    def stop(self):
        """Stop the API server."""
        if self.server:
            self.server.shutdown()
            self.server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Runtime API stopped")

    @property
    def url(self) -> str:
        """Get the API base URL."""
        return f"http://{self.host}:{self.port}"
