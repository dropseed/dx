import os

import click

from plain.runtime import APP_PATH

from .core import Tailwind


@click.group("tailwind")
def cli():
    """Tailwind CSS"""
    pass


@cli.command()
@click.pass_context
def init(ctx):
    """Install Tailwind, create a tailwind.config.js and app/assets/src/tailwind.css"""
    tailwind = Tailwind()

    if not tailwind.is_installed():
        ctx.invoke(update)

    if not tailwind.src_css_path.exists():
        click.secho("Creating Tailwind source CSS...", bold=True)
        tailwind.create_src_css()

    # gitignore


@cli.command()
@click.pass_context
def install(ctx):
    tailwind = Tailwind()

    if not tailwind.is_installed() or tailwind.needs_update():
        version_to_install = tailwind.get_version_from_config()
        if version_to_install:
            click.secho(
                f"Installing Tailwind standalone {version_to_install}...",
                bold=True,
                nl=False,
            )
            version = tailwind.install(version_to_install)
            click.secho(f"Tailwind {version} installed", fg="green")
        else:
            ctx.invoke(update)
    else:
        click.secho("Tailwind already installed", fg="green")


@cli.command()
def update():
    """Update the Tailwind CSS version"""
    tailwind = Tailwind()
    click.secho("Installing Tailwind standalone...", bold=True, nl=True)
    version = tailwind.install()
    click.secho(f"Tailwind {version} installed", fg="green")


@cli.command()
@click.option("--watch", is_flag=True)
@click.option("--minify", is_flag=True)
@click.pass_context
def build(ctx, watch, minify):
    """Compile a Tailwind CSS file"""
    tailwind = Tailwind()

    ctx.invoke(install)

    # https://github.com/tailwindlabs/tailwindcss/issues/15452
    # Remove the .gitignore inside of .venv if it exists, so the sources
    # are picked up correctly...
    if os.path.exists(".venv/.gitignore"):
        click.secho(
            "Removing .venv/.gitignore to fix tailwind bug...", bold=True, fg="yellow"
        )
        os.remove(".venv/.gitignore")

    tailwind.update_plain_sources()

    args = []
    args.append("-i")
    args.append(tailwind.src_css_path)

    args.append("-o")
    args.append(tailwind.dist_css_path)

    click.secho(
        f"Compiling {os.path.relpath(tailwind.src_css_path)} to {os.path.relpath(tailwind.dist_css_path)}...",
        bold=True,
    )

    if watch:
        args.append("--watch")

    if minify:
        args.append("--minify")

    tailwind.invoke(*args, cwd=os.path.dirname(APP_PATH))


if __name__ == "__main__":
    cli()
