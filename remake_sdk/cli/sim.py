"""
Simulation commands: remake sim start|stop|status
"""

import click
import json as json_mod
import sys
import requests


BRIDGE_API_URL = "http://127.0.0.1:8788"


@click.group()
@click.pass_context
def sim(ctx):
    """
    Simulation management commands.

    Control the robot simulator for app development and testing.

    \b
    Commands:
        start   - Start a simulator
        stop    - Stop the active simulator
        status  - Show simulation status
    """
    pass


@sim.command()
@click.option(
    "--simulator", "-s", default=None,
    help="Simulator to use (e.g. gazebo, unity). Uses default if not specified."
)
@click.option(
    "--world", "-w", default=None,
    help="World/environment name (e.g. living_room.world)"
)
@click.option(
    "--headless", is_flag=True,
    help="Run without GUI (for CI/CD)"
)
@click.pass_context
def start(ctx, simulator, world, headless):
    """
    Start a simulator.

    Launches a robot simulator so apps can run against a simulated
    environment. The simulator provides the same ROS2 topics as a
    physical robot.

    \b
    Examples:
        remake sim start
        remake sim start --simulator gazebo
        remake sim start --world kitchen.world
        remake sim start --headless
    """
    if not _is_bridge_running():
        click.echo(
            click.style("App Bridge is not running.", fg="red"), err=True
        )
        click.echo(
            "Start it with: ros2 launch remake_ros2 app_bridge.launch.py",
            err=True,
        )
        sys.exit(1)

    click.echo("Starting simulation...")

    payload = {}
    if simulator:
        payload["simulator"] = simulator
    if world:
        payload["world"] = world
    if headless:
        payload["headless"] = True

    try:
        resp = requests.post(
            f"{BRIDGE_API_URL}/api/sim/start",
            json=payload,
            timeout=30,
        )
        result = resp.json()
    except requests.ConnectionError:
        click.echo(
            click.style("Cannot connect to App Bridge.", fg="red"), err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)

    if result.get("success"):
        sim_name = result.get("simulator", "unknown")
        world_name = result.get("world", "default")
        click.echo()
        click.echo(click.style("Simulation started!", fg="green"))
        click.echo(f"  Simulator:  {sim_name}")
        click.echo(f"  World:      {world_name}")
        click.echo()
        click.echo(
            "Services will automatically use simulation time. "
            "Apps connect normally."
        )
    else:
        message = result.get("message", "Unknown error")
        click.echo(click.style(f"Failed: {message}", fg="red"), err=True)
        sys.exit(1)


@sim.command()
@click.pass_context
def stop(ctx):
    """
    Stop the active simulator.

    Stops any running services that depend on the simulator first,
    then stops the simulator itself.

    \b
    Examples:
        remake sim stop
    """
    if not _is_bridge_running():
        click.echo(
            click.style("App Bridge is not running.", fg="red"), err=True
        )
        sys.exit(1)

    click.echo("Stopping simulation...")

    try:
        resp = requests.post(
            f"{BRIDGE_API_URL}/api/sim/stop",
            timeout=30,
        )
        result = resp.json()
    except requests.ConnectionError:
        click.echo(
            click.style("Cannot connect to App Bridge.", fg="red"), err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)

    if result.get("success"):
        sim_name = result.get("simulator")
        if sim_name:
            click.echo(
                click.style(f"Simulator '{sim_name}' stopped.", fg="green")
            )
        else:
            click.echo("No simulator was running.")
    else:
        message = result.get("message", "Unknown error")
        click.echo(click.style(f"Failed: {message}", fg="red"), err=True)
        sys.exit(1)


@sim.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def status(ctx, as_json):
    """
    Show simulation status.

    \b
    Examples:
        remake sim status
        remake sim status --json
    """
    if not _is_bridge_running():
        if as_json:
            click.echo(json_mod.dumps({
                "active": False,
                "bridge_running": False,
            }, indent=2))
        else:
            click.echo(
                click.style("App Bridge is not running.", fg="red"), err=True
            )
            click.echo(
                "Start it with: ros2 launch remake_ros2 app_bridge.launch.py",
                err=True,
            )
        sys.exit(1)

    try:
        resp = requests.get(
            f"{BRIDGE_API_URL}/api/sim/status",
            timeout=5,
        )
        result = resp.json()
    except requests.ConnectionError:
        click.echo(
            click.style("Cannot connect to App Bridge.", fg="red"), err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"Error: {e}", fg="red"), err=True)
        sys.exit(1)

    if as_json:
        click.echo(json_mod.dumps(result, indent=2))
        return

    click.echo("Simulation Status")
    click.echo("=" * 40)
    click.echo()

    if result.get("active"):
        click.echo(f"  Status:     {click.style('running', fg='green')}")
        click.echo(f"  Simulator:  {result.get('simulator', 'unknown')}")
        click.echo(f"  State:      {result.get('state', 'unknown')}")
        click.echo(f"  World:      {result.get('world', 'unknown')}")
        if "uptime_s" in result:
            uptime = result["uptime_s"]
            mins, secs = divmod(uptime, 60)
            click.echo(f"  Uptime:     {mins}m {secs}s")
        if result.get("error"):
            click.echo(
                f"  Error:      {click.style(result['error'], fg='red')}"
            )
    else:
        click.echo(f"  Status:     {click.style('not running', fg='yellow')}")

    available = result.get("available_simulators", [])
    default = result.get("default_simulator")
    if available:
        sim_list = []
        for s in available:
            if s == default:
                sim_list.append(f"{s} (default)")
            else:
                sim_list.append(s)
        click.echo(f"  Available:  {', '.join(sim_list)}")

    click.echo()


def _is_bridge_running() -> bool:
    """Check if the App Bridge HTTP API is responding."""
    try:
        resp = requests.get(f"{BRIDGE_API_URL}/api/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False
