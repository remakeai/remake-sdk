"""
Remake CLI - Command-line interface for robot management.

Commands:
    remake pair      - Pair robot with platform
    remake unpair    - Remove platform pairing
    remake status    - Show connection status
    remake connect   - Connect and listen for commands
    remake app       - App management (launch, stop, list)
"""

import click
import asyncio
import sys
from functools import wraps

from .pair import pair, unpair
from .status import status
from .connect import connect
from .app import app
from .runtime import runtime


def async_command(f):
    """Decorator to run async functions in Click commands."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper


@click.group()
@click.version_option(version="2.0.0a1", prog_name="remake")
@click.option("--debug/--no-debug", default=False, help="Enable debug logging")
@click.pass_context
def cli(ctx, debug):
    """Remake CLI - Robot management and app control."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)


# Register commands
cli.add_command(pair)
cli.add_command(unpair)
cli.add_command(status)
cli.add_command(connect)
cli.add_command(app)
cli.add_command(runtime)


def main():
    """Entry point for the CLI."""
    try:
        cli(obj={})
    except KeyboardInterrupt:
        click.echo("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
