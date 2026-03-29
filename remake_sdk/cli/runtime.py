"""
Runtime commands: remake runtime start|stop|status
"""

import click
import sys
import os
import signal
import time
import requests
from pathlib import Path


RUNTIME_API_URL = "http://127.0.0.1:8787"
PID_FILE = Path("/tmp/remake-runtime.pid")


@click.group()
@click.pass_context
def runtime(ctx):
    """
    Runtime management commands.

    The runtime is the core daemon that manages apps and platform connection.

    \b
    Commands:
        start   - Start the runtime daemon
        stop    - Stop the runtime daemon
        status  - Show runtime status
    """
    pass


@runtime.command()
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (don't daemonize)")
@click.option("--no-platform", is_flag=True, help="Don't connect to platform")
@click.option("--port", default=8787, help="API port (default: 8787)")
@click.option("--backend", type=click.Choice(["agent", "podman", "auto"]), default=None,
              help="Container backend (default: from config or auto)")
@click.option("--agent-url", default=None, help="Host Agent URL (implies --backend agent)")
@click.pass_context
def start(ctx, foreground, no_platform, port, backend, agent_url):
    """
    Start the runtime daemon.

    The runtime manages app lifecycle and platform connection.
    By default, runs as a background daemon.

    \b
    Examples:
        remake runtime start
        remake runtime start --foreground
        remake runtime start --no-platform
        remake runtime start --backend agent
        remake runtime start --backend podman
        remake runtime start --agent-url http://192.168.1.50:8785
    """
    from ..runtime.daemon import RuntimeDaemon, RuntimeConfig, run_daemon

    # Check if already running
    if RuntimeDaemon.is_running(PID_FILE):
        pid = RuntimeDaemon.get_pid(PID_FILE)
        click.echo(f"Runtime is already running (PID: {pid})")
        click.echo(f"API: {RUNTIME_API_URL}")
        return

    # --agent-url implies --backend agent
    if agent_url and not backend:
        backend = "agent"

    config = RuntimeConfig(
        api_port=port,
        connect_to_platform=not no_platform,
        pid_file=PID_FILE,
        backend=backend,
        agent_url=agent_url,
    )

    if foreground:
        # Run in foreground
        click.echo("Starting runtime in foreground...")
        click.echo(f"API: http://127.0.0.1:{port}")
        click.echo("Press Ctrl+C to stop.")
        click.echo()

        import logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

        try:
            run_daemon(config)
        except KeyboardInterrupt:
            click.echo("\nRuntime stopped.")
    else:
        # Daemonize
        click.echo("Starting runtime daemon...")

        # Fork to background
        pid = os.fork()
        if pid > 0:
            # Parent - wait a bit and check if started
            time.sleep(1)
            if is_runtime_healthy():
                click.echo(click.style("Runtime started!", fg="green"))
                click.echo(f"PID: {RuntimeDaemon.get_pid(PID_FILE)}")
                click.echo(f"API: http://127.0.0.1:{port}")
            else:
                click.echo(click.style("Runtime failed to start", fg="red"), err=True)
                sys.exit(1)
        else:
            # Child - become daemon
            os.setsid()

            # Redirect stdio
            sys.stdin = open(os.devnull, 'r')
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')

            # Run daemon
            run_daemon(config)


@runtime.command()
@click.option("--force", "-f", is_flag=True, help="Force stop (SIGKILL)")
@click.pass_context
def stop(ctx, force):
    """
    Stop the runtime daemon.

    \b
    Examples:
        remake runtime stop
        remake runtime stop --force
    """
    from ..runtime.daemon import RuntimeDaemon

    if not RuntimeDaemon.is_running(PID_FILE):
        click.echo("Runtime is not running.")
        return

    pid = RuntimeDaemon.get_pid(PID_FILE)
    if not pid:
        click.echo("Could not determine runtime PID.")
        return

    click.echo(f"Stopping runtime (PID: {pid})...")

    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)

        # Wait for process to exit
        for _ in range(30):  # Wait up to 3 seconds
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break

        # Check if stopped
        if not RuntimeDaemon.is_running(PID_FILE):
            click.echo(click.style("Runtime stopped.", fg="green"))
            # Clean up PID file if still exists
            if PID_FILE.exists():
                PID_FILE.unlink()
        else:
            click.echo(click.style("Runtime did not stop. Try --force", fg="yellow"), err=True)
            sys.exit(1)

    except ProcessLookupError:
        click.echo("Runtime process not found (already stopped).")
        if PID_FILE.exists():
            PID_FILE.unlink()
    except PermissionError:
        click.echo("Permission denied. Try with sudo.", err=True)
        sys.exit(1)


@runtime.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status(ctx, as_json):
    """
    Show runtime status.

    \b
    Examples:
        remake runtime status
        remake runtime status --json
    """
    import json as json_mod
    from ..runtime.daemon import RuntimeDaemon

    is_running = RuntimeDaemon.is_running(PID_FILE)
    pid = RuntimeDaemon.get_pid(PID_FILE) if is_running else None

    # Try to get detailed status from API
    api_status = None
    if is_running:
        try:
            resp = requests.get(f"{RUNTIME_API_URL}/status", timeout=2)
            if resp.status_code == 200:
                api_status = resp.json()
        except:
            pass

    if as_json:
        data = {
            "running": is_running,
            "pid": pid,
            "api_url": RUNTIME_API_URL if is_running else None,
            "apps": api_status.get("apps") if api_status else None
        }
        click.echo(json_mod.dumps(data, indent=2))
        return

    click.echo("Runtime Status")
    click.echo("=" * 40)
    click.echo()

    if is_running:
        click.echo(f"  Status:  {click.style('running', fg='green')}")
        click.echo(f"  PID:     {pid}")
        click.echo(f"  API:     {RUNTIME_API_URL}")

        if api_status:
            apps = api_status.get("apps", {})
            click.echo(f"  Apps:    {apps.get('installed', 0)} installed, {apps.get('running', 0)} running")
    else:
        click.echo(f"  Status:  {click.style('stopped', fg='yellow')}")
        click.echo()
        click.echo("  Start with: remake runtime start")

    click.echo()


def is_runtime_healthy() -> bool:
    """Check if runtime API is responding."""
    try:
        resp = requests.get(f"{RUNTIME_API_URL}/health", timeout=2)
        return resp.status_code == 200
    except:
        return False
