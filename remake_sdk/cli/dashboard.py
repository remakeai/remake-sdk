"""
Dashboard command: remake dashboard
"""

import click
import sys
import webbrowser


@click.command()
@click.option("--port", "-p", default=8080, help="Dashboard port (default: 8080)")
@click.option("--no-open", is_flag=True, help="Don't open browser automatically")
@click.option("--url-only", is_flag=True, help="Show URL without starting server")
@click.pass_context
def dashboard(ctx, port, no_open, url_only):
    """
    Open the robot dashboard web UI.

    Starts a local web server with a dashboard for:
    - Viewing running and installed apps
    - Launching and stopping apps
    - Viewing app logs
    - Manual robot control

    \b
    Examples:
        remake dashboard
        remake dashboard --port 9000
        remake dashboard --no-open
        remake dashboard --url-only
    """
    url = f"http://localhost:{port}"

    if url_only:
        click.echo(url)
        return

    click.echo(f"Starting Remake Dashboard on {url}")
    click.echo()

    # Open browser unless --no-open
    if not no_open:
        click.echo("Opening browser...")
        try:
            webbrowser.open(url)
        except Exception as e:
            click.echo(f"Could not open browser: {e}")

    click.echo("Press Ctrl+C to stop the dashboard.")
    click.echo()

    try:
        from ..dashboard import run_dashboard
        run_dashboard(port=port, debug=ctx.obj.get("debug", False))
    except ImportError as e:
        click.echo(f"Error: Could not import dashboard module: {e}", err=True)
        click.echo("Make sure Flask is installed: pip install flask")
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nDashboard stopped.")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
