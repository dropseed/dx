import os
import subprocess
import sys
import tomllib
from importlib.util import find_spec
from pathlib import Path

import click

from plain.cli.print import print_event

from ..services import Services


def install_git_hook():
    hook_path = os.path.join(".git", "hooks", "pre-commit")
    if os.path.exists(hook_path):
        print("pre-commit hook already exists")
    else:
        with open(hook_path, "w") as f:
            f.write(
                """#!/bin/sh
plain pre-commit"""
            )
        os.chmod(hook_path, 0o755)
        print("pre-commit hook installed")


@click.command()
@click.option("--install", is_flag=True)
def cli(install):
    """Git pre-commit checks"""
    if install:
        install_git_hook()
        return

    pyproject = Path("pyproject.toml")

    with Services():
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                pyproject = tomllib.load(f)
            for name, data in (
                pyproject.get("tool", {})
                .get("plain", {})
                .get("pre-commit", {})
                .get("run", {})
            ).items():
                cmd = data["cmd"]
                print_event(f"Custom: {name} -> {cmd}")
                result = subprocess.run(cmd, shell=True)
                if result.returncode != 0:
                    sys.exit(result.returncode)

        # Run this first since it's probably the most likely to fail
        if find_spec("plain.code"):
            check_short("Running plain code checks", "plain", "code", "check")

        if Path("uv.lock").exists():
            check_short("Checking uv.lock", "uv", "lock", "--check")

        if plain_db_connected():
            check_short(
                "Running preflight checks",
                "plain",
                "preflight",
                "--database",
                "default",
            )
            check_short("Checking Plain migrations", "plain", "migrate", "--check")
            check_short(
                "Checking for Plain models missing migrations",
                "plain",
                "makemigrations",
                "--dry-run",
                "--check",
            )
        else:
            check_short("Running Plain checks (without database)", "plain", "preflight")
            click.secho("--> Skipping migration checks", bold=True, fg="yellow")

        print_event("Running plain build")
        result = subprocess.run(["plain", "build"])
        if result.returncode != 0:
            sys.exit(result.returncode)

        if find_spec("plain.pytest"):
            print_event("Running tests")
            result = subprocess.run(["plain", "test"])
            if result.returncode != 0:
                sys.exit(result.returncode)


def plain_db_connected():
    result = subprocess.run(
        [
            "plain",
            "models",
            "show-migrations",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def check_short(message, *args):
    print_event(message, newline=False)
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        click.secho("✘", fg="red")
        click.secho(result.stdout.decode("utf-8"))
        sys.exit(1)
    else:
        click.secho("✔", fg="green")
