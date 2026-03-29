"""
Host Agent HTTP server.

REST API for managing app containers from inside the robot container.
"""

import logging
import signal
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from typing import Optional

from .config import AgentConfig
from .docker_backend import DockerBackend

logger = logging.getLogger(__name__)


class AgentHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Host Agent API."""

    backend: DockerBackend = None

    def log_message(self, format, *args):
        logger.debug(f"Agent: {args[0]}")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Optional[dict]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        try:
            body = self.rfile.read(content_length)
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._send_json({"status": "healthy", "agent": "remake-agent"})

        elif path == "/containers":
            containers = self.backend.list_containers()
            self._send_json({"success": True, "containers": containers})

        elif path.startswith("/containers/") and path.endswith("/logs"):
            app_id = path.split("/")[2]
            tail = int(qs.get("tail", [100])[0])
            logs = self.backend.get_logs(app_id, tail=tail)
            if logs is not None:
                self._send_json({"success": True, "logs": logs})
            else:
                self._send_json({"success": False, "error": "not_found"}, 404)

        elif path.startswith("/containers/") and path.count("/") == 2:
            app_id = path.split("/")[2]
            container = self.backend.get_container(app_id)
            if container:
                self._send_json({"success": True, "container": container})
            else:
                self._send_json({"success": False, "error": "not_found"}, 404)

        elif path.startswith("/images/"):
            image = unquote(path[len("/images/"):])
            exists = self.backend.image_exists(image)
            self._send_json({"exists": exists})

        else:
            self._send_json({"error": "not_found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/containers/pull":
            body = self._read_json()
            if not body or not body.get("image"):
                self._send_json({"success": False, "error": "missing image"}, 400)
                return
            result = self.backend.pull(body["image"])
            status = 200 if result.get("success") else 500
            self._send_json(result, status)

        elif path == "/containers/create":
            body = self._read_json()
            if not body or not body.get("app_id") or not body.get("image"):
                self._send_json({"success": False, "error": "missing app_id or image"}, 400)
                return
            result = self.backend.create_container(body)
            status = 200 if result.get("success") else 500
            self._send_json(result, status)

        elif path.startswith("/containers/") and path.endswith("/stop"):
            app_id = path.split("/")[2]
            body = self._read_json() or {}
            force = body.get("force", False)
            result = self.backend.stop_container(app_id, force=force)
            self._send_json(result)

        elif path == "/volumes/create":
            body = self._read_json() or {}
            app_id = body.get("name") or body.get("app_id")
            if not app_id:
                self._send_json({"success": False, "error": "missing name"}, 400)
                return
            dirs = self.backend.ensure_app_dirs(app_id)
            self._send_json({"success": True, "dirs": dirs})

        else:
            self._send_json({"error": "not_found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/containers/") and path.count("/") == 2:
            app_id = path.split("/")[2]
            result = self.backend.remove_container(app_id)
            self._send_json(result)

        elif path.startswith("/images/"):
            image = unquote(path[len("/images/"):])
            success = self.backend.remove_image(image)
            self._send_json({"success": success})

        elif path.startswith("/volumes/"):
            app_id = path.split("/")[2]
            self.backend.remove_app_dirs(app_id)
            self._send_json({"success": True})

        else:
            self._send_json({"error": "not_found"}, 404)


def run_agent(config: Optional[AgentConfig] = None):
    """Run the Host Agent server (blocking)."""
    config = config or AgentConfig.load()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    logger.info(f"Remake Host Agent v0.1.0")
    logger.info(f"Container runtime: {config.container_runtime}")
    logger.info(f"Network: {config.network}")
    logger.info(f"Data root: {config.data_root}")

    # Initialize backend
    backend = DockerBackend(
        runtime=config.container_runtime,
        network=config.network,
        data_root=config.data_root,
        default_memory=config.default_memory,
        default_cpus=config.default_cpus,
    )

    # Ensure shared network exists
    try:
        backend.ensure_network()
    except Exception as e:
        logger.warning(f"Could not create network {config.network}: {e}")

    # Set backend on handler
    AgentHandler.backend = backend

    # Start server
    server = HTTPServer((config.host, config.port), AgentHandler)
    logger.info(f"Listening on http://{config.host}:{config.port}")

    # Graceful shutdown
    def shutdown(signum, frame):
        logger.info("Shutting down...")
        backend.cleanup_all()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Host Agent stopped")
