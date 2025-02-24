# plain.dev

A single command that runs everything you need for local development.

![Plain dev command example](https://github.com/dropseed/plain/assets/649496/3643bb64-a99b-4a8e-adab-8c6b81791ea9)

The `plain.dev` package can be [installed from PyPI](https://pypi.org/project/plain.dev/), and does *not* need to be added to `INSTALLED_PACKAGES`.

- [`plain dev`](#plain-dev)
- [`plain dev services`](#plain-dev-services)
- [`plain pre-commit`](#plain-pre-commit)
- [`plain contrib`](#plain-contrib)
- [VS Code debugging](#vscode-debugging)

## `plain dev`

The `plain dev` command does several things:

- Sets `PLAIN_CSRF_TRUSTED_ORIGINS` to localhost by default
- Runs `plain preflight` to check for any issues
- Executes any pending model migrations
- Starts `gunicorn` with `--reload`
- Runs `plain tailwind build --watch`, if `plain.tailwind` is installed
- Any custom process defined in `pyproject.toml` at `tool.plain.dev.run`
- Necessary services (ex. Postgres) defined in `pyproject.toml` at `tool.plain.dev.services`

### Services

Use services to define databases or other processes that your app *needs* to be functional. The services will be started automatically in `plain dev`, but also in `plain pre-commit` (so preflight and tests have a database).

Ultimately, how you run your development database is up to you. But a recommended starting point is to use Docker:

```toml
# pyproject.toml
[tool.plain.dev.services]
postgres = {cmd = "docker run --name app-postgres --rm -p 54321:5432 -v $(pwd)/.plain/dev/pgdata:/var/lib/postgresql/data -e POSTGRES_PASSWORD=postgres postgres:15 postgres"}
```

### Custom processes

Unlike [services](#services), custom processes are *only* run during `plain dev`. This is a good place to run something like [ngrok](https://ngrok.com/) or a [Plain worker](../../../plain-worker), which you might need to use your local site, but don't need running for executing tests, for example.

```toml
# pyproject.toml
[tool.plain.dev.run]
ngrok = {command = "ngrok http $PORT"}
```

## `plain dev services`

Starts your [services](#services) by themselves.

## `plain pre-commit`

A built-in pre-commit hook that can be installed with `plain pre-commit --install`.

Runs:

- Custom commands defined in `pyproject.toml` at `tool.plain.pre-commit.run`
- `plain code check`, if [`plain.code`](https://plainframework.com/docs/plain-code/plain/code/) is installed
- `uv lock --locked`, if using uv
- `plain preflight --database default`
- `plain migrate --check`
- `plain makemigrations --dry-run --check`
- `plain build`
- `plain test`

## VS Code debugging

![Debug Plain with VS Code](https://github.com/dropseed/plain-public/assets/649496/250138b6-7702-4ab6-bf38-e0c8e3c56d06)

Since `plain dev` runs multiple processes at once, the regular [pdb](https://docs.python.org/3/library/pdb.html) debuggers don't quite work.

Instead, we include [microsoft/debugpy](https://github.com/microsoft/debugpy) and an `attach` function to make it even easier to use VS Code's debugger.

First, import and run the `debug.attach()` function:

```python
class HomeView(TemplateView):
    template_name = "home.html"

    def get_template_context(self):
        context = super().get_template_context()

        # Make sure the debugger is attached (will need to be if runserver reloads)
        from plain.dev import debug; debug.attach()

        # Add a breakpoint (or use the gutter in VS Code to add one)
        breakpoint()

        return context
```

When you load the page, you'll see "Waiting for debugger to attach...".

You can then run the VS Code debugger and attach to an existing Python process, at localhost:5678.
