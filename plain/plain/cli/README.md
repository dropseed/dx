# CLI

The `plain` CLI loads commands from Plain itself, and any `INSTALLED_PACKAGES`.

Commands are written using [Click]((https://click.palletsprojects.com/en/8.1.x/))
(one of Plain's few dependencies),
which has been one of those most popular CLI frameworks in Python for a long time now.

## Built-in commands

### `plain shell`

Open a Python shell with the Plain loaded.

To auto-load models or run other code at shell launch,
create an `app/shell.py` and it will be imported automatically.

```python
# app/shell.py
from organizations.models import Organization

__all__ = [
    "Organization",
]
```

### `plain build`

Compile static assets (used in the deploy/production process).

Automatically runs `plain tailwind build` if [plain-tailwind](https://plainframework.com/docs/plain-tailwind/) is installed.

### `plain run`

Run a Python script in the context of your app.

### `plain preflight`

Run preflight checks to ensure your app is ready to run.

### `plain create`

Create a new local package.

### `plain setting`

View the runtime value of a named setting.

## Adding commands

### Add an `app/cli.py`

You can add "root" commands to your app by defining a `cli` function in `app/cli.py`.

```python
import click


@click.group()
def cli():
    pass


@cli.command()
def custom_command():
    click.echo("An app command!")
```

Then you can run the command with `plain`.

```bash
$ plain custom-command
An app command!
```

### Add CLI commands to your local packages

Any package in `INSTALLED_PACKAGES` can define CLI commands by creating a `cli.py` in the root of the package.
In `cli.py`, create a command or group of commands named `cli`.

```python
import click


@click.group()
def cli():
    pass


@cli.command()
def hello():
    click.echo("Hello, world!")
```

Plain will use the name of the package in the CLI,
then any commands you defined.

```bash
$ plain <pkg> hello
Hello, world!
```

### Add CLI commands to published packages

Some packages, like [plain-dev](https://plainframework.com/docs/plain-dev/),
never show up in `INSTALLED_PACKAGES` but still have CLI commands.
These are detected via Python entry points.

An example with `pyproject.toml` and UV:

```toml
# pyproject.toml
[project.entry-points."plain.cli"]
"dev" = "plain.dev:cli"
"pre-commit" = "plain.dev.precommit:cli"
"contrib" = "plain.dev.contribute:cli"
```
