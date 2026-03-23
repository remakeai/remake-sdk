"""
App Registry - Track installed apps in local SQLite database.
"""

import sqlite3
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List
from datetime import datetime


@dataclass
class PortMapping:
    """Container port mapping."""
    container: int
    host: int
    protocol: str = "tcp"
    description: Optional[str] = None


@dataclass
class InstalledApp:
    """Metadata for an installed app."""
    app_id: str
    version: str
    container_image: str
    name: Optional[str] = None
    description: Optional[str] = None
    entitlements: Optional[List[str]] = None
    installed_at: Optional[str] = None
    source: str = "local"  # "local" or "platform"
    ports: Optional[List[PortMapping]] = None
    environment: Optional[dict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Convert PortMapping objects to dicts
        if self.ports:
            d['ports'] = [asdict(p) if isinstance(p, PortMapping) else p for p in self.ports]
        return d


class AppRegistry:
    """
    Local registry of installed apps.

    Stores app metadata in SQLite for persistence across restarts.
    """

    DEFAULT_PATH = Path.home() / ".config" / "remake" / "apps.db"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or self.DEFAULT_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS installed_apps (
                    app_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    container_image TEXT NOT NULL,
                    name TEXT,
                    description TEXT,
                    entitlements TEXT,
                    installed_at TEXT NOT NULL,
                    source TEXT DEFAULT 'local',
                    ports TEXT,
                    environment TEXT
                )
            """)
            # Migrate: add new columns if they don't exist
            try:
                conn.execute("ALTER TABLE installed_apps ADD COLUMN ports TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE installed_apps ADD COLUMN environment TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            conn.commit()

    def add(self, app: InstalledApp) -> bool:
        """Add or update an installed app."""
        # Serialize ports
        ports_json = None
        if app.ports:
            ports_json = json.dumps([
                asdict(p) if isinstance(p, PortMapping) else p
                for p in app.ports
            ])

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO installed_apps
                (app_id, version, container_image, name, description, entitlements, installed_at, source, ports, environment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                app.app_id,
                app.version,
                app.container_image,
                app.name,
                app.description,
                json.dumps(app.entitlements) if app.entitlements else None,
                app.installed_at or datetime.utcnow().isoformat(),
                app.source,
                ports_json,
                json.dumps(app.environment) if app.environment else None,
            ))
            conn.commit()
        return True

    def remove(self, app_id: str) -> bool:
        """Remove an app from registry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM installed_apps WHERE app_id = ?",
                (app_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get(self, app_id: str) -> Optional[InstalledApp]:
        """Get app by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM installed_apps WHERE app_id = ?",
                (app_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_app(row)
        return None

    def list_all(self) -> List[InstalledApp]:
        """List all installed apps."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM installed_apps ORDER BY installed_at DESC"
            )
            return [self._row_to_app(row) for row in cursor.fetchall()]

    def _row_to_app(self, row: sqlite3.Row) -> InstalledApp:
        """Convert database row to InstalledApp."""
        entitlements = None
        if row["entitlements"]:
            try:
                entitlements = json.loads(row["entitlements"])
            except json.JSONDecodeError:
                pass

        ports = None
        try:
            ports_raw = row["ports"]
            if ports_raw:
                ports_data = json.loads(ports_raw)
                ports = [PortMapping(**p) for p in ports_data]
        except (KeyError, json.JSONDecodeError):
            pass

        environment = None
        try:
            env_raw = row["environment"]
            if env_raw:
                environment = json.loads(env_raw)
        except (KeyError, json.JSONDecodeError):
            pass

        return InstalledApp(
            app_id=row["app_id"],
            version=row["version"],
            container_image=row["container_image"],
            name=row["name"],
            description=row["description"],
            entitlements=entitlements,
            installed_at=row["installed_at"],
            source=row["source"],
            ports=ports,
            environment=environment,
        )

    def is_installed(self, app_id: str) -> bool:
        """Check if app is installed."""
        return self.get(app_id) is not None
