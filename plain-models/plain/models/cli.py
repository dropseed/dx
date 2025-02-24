import os
import subprocess
import sys
import time
from itertools import takewhile

import click

from plain.packages import packages_registry
from plain.runtime import settings
from plain.utils.text import Truncator

from . import migrations
from .backups.cli import cli as backups_cli
from .backups.cli import create_backup
from .db import DEFAULT_DB_ALIAS, OperationalError, connections, router
from .migrations.autodetector import MigrationAutodetector
from .migrations.executor import MigrationExecutor
from .migrations.loader import AmbiguityError, MigrationLoader
from .migrations.migration import Migration, SwappableTuple
from .migrations.optimizer import MigrationOptimizer
from .migrations.questioner import (
    InteractiveMigrationQuestioner,
    MigrationQuestioner,
    NonInteractiveMigrationQuestioner,
)
from .migrations.recorder import MigrationRecorder
from .migrations.state import ModelState, ProjectState
from .migrations.utils import get_migration_name_timestamp
from .migrations.writer import MigrationWriter
from .registry import models_registry


@click.group()
def cli():
    pass


cli.add_command(backups_cli)


@cli.command()
@click.option(
    "--database",
    default=DEFAULT_DB_ALIAS,
    help=(
        "Nominates a database onto which to open a shell. Defaults to the "
        '"default" database.'
    ),
)
@click.argument("parameters", nargs=-1)
def db_shell(database, parameters):
    """Runs the command-line client for specified database, or the default database if none is provided."""
    connection = connections[database]
    try:
        connection.client.runshell(parameters)
    except FileNotFoundError:
        # Note that we're assuming the FileNotFoundError relates to the
        # command missing. It could be raised for some other reason, in
        # which case this error message would be inaccurate. Still, this
        # message catches the common case.
        click.secho(
            f"You appear not to have the {connection.client.executable_name!r} program installed or on your path.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.secho(
            '"{}" returned non-zero exit status {}.'.format(
                " ".join(e.cmd),
                e.returncode,
            ),
            fg="red",
            err=True,
        )
        sys.exit(e.returncode)


@cli.command()
def db_wait():
    """Wait for the database to be ready"""
    attempts = 0
    while True:
        attempts += 1
        waiting_for = []

        for conn in connections.all():
            try:
                conn.ensure_connection()
            except OperationalError:
                waiting_for.append(conn.alias)

        if waiting_for:
            click.secho(
                f"Waiting for database (attempt {attempts}): {', '.join(waiting_for)}",
                fg="yellow",
            )
            time.sleep(1.5)
        else:
            click.secho(f"Database ready: {', '.join(connections)}", fg="green")
            break


@cli.command()
@click.argument("package_labels", nargs=-1)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Just show what migrations would be made; don't actually write them.",
)
@click.option("--merge", is_flag=True, help="Enable fixing of migration conflicts.")
@click.option("--empty", is_flag=True, help="Create an empty migration.")
@click.option(
    "--noinput",
    "--no-input",
    "no_input",
    is_flag=True,
    help="Tells Plain to NOT prompt the user for input of any kind.",
)
@click.option("-n", "--name", help="Use this name for migration file(s).")
@click.option(
    "--check",
    is_flag=True,
    help="Exit with a non-zero status if model changes are missing migrations and don't actually write them.",
)
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def makemigrations(
    package_labels, dry_run, merge, empty, no_input, name, check, verbosity
):
    """Creates new migration(s) for packages."""

    written_files = []
    interactive = not no_input
    migration_name = name
    check_changes = check

    def log(msg, level=1):
        if verbosity >= level:
            click.echo(msg)

    def write_migration_files(changes, update_previous_migration_paths=None):
        """Take a changes dict and write them out as migration files."""
        directory_created = {}
        for package_label, package_migrations in changes.items():
            log(
                click.style(f"Migrations for '{package_label}':", fg="cyan", bold=True),
                level=1,
            )
            for migration in package_migrations:
                writer = MigrationWriter(migration)
                migration_string = os.path.relpath(writer.path)
                log(f"  {click.style(migration_string, fg='yellow')}\n", level=1)
                for operation in migration.operations:
                    log(f"    - {operation.describe()}", level=1)

                if not dry_run:
                    migrations_directory = os.path.dirname(writer.path)
                    if not directory_created.get(package_label):
                        os.makedirs(migrations_directory, exist_ok=True)
                        init_path = os.path.join(migrations_directory, "__init__.py")
                        if not os.path.isfile(init_path):
                            open(init_path, "w").close()
                        directory_created[package_label] = True

                    migration_string = writer.as_string()
                    with open(writer.path, "w", encoding="utf-8") as fh:
                        fh.write(migration_string)
                        written_files.append(writer.path)

                    if update_previous_migration_paths:
                        prev_path = update_previous_migration_paths[package_label]
                        if writer.needs_manual_porting:
                            log(
                                click.style(
                                    f"Updated migration {migration_string} requires manual porting.\n"
                                    f"Previous migration {os.path.relpath(prev_path)} was kept and "
                                    f"must be deleted after porting functions manually.",
                                    fg="yellow",
                                ),
                                level=1,
                            )
                        else:
                            os.remove(prev_path)
                            log(f"Deleted {os.path.relpath(prev_path)}", level=1)
                elif verbosity >= 3:
                    log(
                        click.style(
                            f"Full migrations file '{writer.filename}':",
                            fg="cyan",
                            bold=True,
                        ),
                        level=3,
                    )
                    log(writer.as_string(), level=3)

    def handle_merge(loader, conflicts):
        """Handle merging conflicting migrations."""
        if interactive:
            questioner = InteractiveMigrationQuestioner()
        else:
            questioner = MigrationQuestioner(defaults={"ask_merge": True})

        for package_label, migration_names in conflicts.items():
            log(click.style(f"Merging {package_label}", fg="cyan", bold=True), level=1)

            merge_migrations = []
            for migration_name in migration_names:
                migration = loader.get_migration(package_label, migration_name)
                migration.ancestry = [
                    mig
                    for mig in loader.graph.forwards_plan(
                        (package_label, migration_name)
                    )
                    if mig[0] == migration.package_label
                ]
                merge_migrations.append(migration)

            def all_items_equal(seq):
                return all(item == seq[0] for item in seq[1:])

            merge_migrations_generations = zip(*(m.ancestry for m in merge_migrations))
            common_ancestor_count = sum(
                1 for _ in takewhile(all_items_equal, merge_migrations_generations)
            )
            if not common_ancestor_count:
                raise ValueError(f"Could not find common ancestor of {migration_names}")

            for migration in merge_migrations:
                migration.branch = migration.ancestry[common_ancestor_count:]
                migrations_ops = (
                    loader.get_migration(node_package, node_name).operations
                    for node_package, node_name in migration.branch
                )
                migration.merged_operations = sum(migrations_ops, [])

            for migration in merge_migrations:
                log(click.style(f"  Branch {migration.name}", fg="yellow"), level=1)
                for operation in migration.merged_operations:
                    log(f"    - {operation.describe()}", level=1)

            if questioner.ask_merge(package_label):
                numbers = [
                    MigrationAutodetector.parse_number(migration.name)
                    for migration in merge_migrations
                ]
                biggest_number = (
                    max(x for x in numbers if x is not None) if numbers else 0
                )

                subclass = type(
                    "Migration",
                    (Migration,),
                    {
                        "dependencies": [
                            (package_label, migration.name)
                            for migration in merge_migrations
                        ],
                    },
                )

                parts = [f"{biggest_number + 1:04d}"]
                if migration_name:
                    parts.append(migration_name)
                else:
                    parts.append("merge")
                    leaf_names = "_".join(
                        sorted(migration.name for migration in merge_migrations)
                    )
                    if len(leaf_names) > 47:
                        parts.append(get_migration_name_timestamp())
                    else:
                        parts.append(leaf_names)

                new_migration_name = "_".join(parts)
                new_migration = subclass(new_migration_name, package_label)
                writer = MigrationWriter(new_migration)

                if not dry_run:
                    with open(writer.path, "w", encoding="utf-8") as fh:
                        fh.write(writer.as_string())
                    log(f"\nCreated new merge migration {writer.path}", level=1)
                elif verbosity == 3:
                    log(
                        click.style(
                            f"Full merge migrations file '{writer.filename}':",
                            fg="cyan",
                            bold=True,
                        ),
                        level=3,
                    )
                    log(writer.as_string(), level=3)

    # Validate package labels
    package_labels = set(package_labels)
    has_bad_labels = False
    for package_label in package_labels:
        try:
            packages_registry.get_package_config(package_label)
        except LookupError as err:
            click.echo(str(err), err=True)
            has_bad_labels = True
    if has_bad_labels:
        sys.exit(2)

    # Load the current graph state
    loader = MigrationLoader(None, ignore_no_migrations=True)

    # Raise an error if any migrations are applied before their dependencies.
    consistency_check_labels = {
        config.label for config in packages_registry.get_package_configs()
    }
    # Non-default databases are only checked if database routers used.
    aliases_to_check = connections if settings.DATABASE_ROUTERS else [DEFAULT_DB_ALIAS]
    for alias in sorted(aliases_to_check):
        connection = connections[alias]
        if connection.settings_dict["ENGINE"] != "plain.models.backends.dummy" and any(
            router.allow_migrate(
                connection.alias, package_label, model_name=model._meta.object_name
            )
            for package_label in consistency_check_labels
            for model in models_registry.get_models(package_label=package_label)
        ):
            loader.check_consistent_history(connection)

    # Check for conflicts
    conflicts = loader.detect_conflicts()
    if package_labels:
        conflicts = {
            package_label: conflict
            for package_label, conflict in conflicts.items()
            if package_label in package_labels
        }

    if conflicts and not merge:
        name_str = "; ".join(
            "{} in {}".format(", ".join(names), package)
            for package, names in conflicts.items()
        )
        raise click.ClickException(
            f"Conflicting migrations detected; multiple leaf nodes in the "
            f"migration graph: ({name_str}).\nTo fix them run "
            f"'python manage.py makemigrations --merge'"
        )

    # Handle merge if requested
    if merge and conflicts:
        return handle_merge(loader, conflicts)

    # Set up questioner
    if interactive:
        questioner = InteractiveMigrationQuestioner(
            specified_packages=package_labels,
            dry_run=dry_run,
        )
    else:
        questioner = NonInteractiveMigrationQuestioner(
            specified_packages=package_labels,
            dry_run=dry_run,
            verbosity=verbosity,
        )

    # Set up autodetector
    autodetector = MigrationAutodetector(
        loader.project_state(),
        ProjectState.from_models_registry(models_registry),
        questioner,
    )

    # Handle empty migrations if requested
    if empty:
        if not package_labels:
            raise click.ClickException(
                "You must supply at least one package label when using --empty."
            )
        changes = {
            package: [Migration("custom", package)] for package in package_labels
        }
        changes = autodetector.arrange_for_graph(
            changes=changes,
            graph=loader.graph,
            migration_name=migration_name,
        )
        write_migration_files(changes)
        return

    # Detect changes
    changes = autodetector.changes(
        graph=loader.graph,
        trim_to_packages=package_labels or None,
        convert_packages=package_labels or None,
        migration_name=migration_name,
    )

    if not changes:
        log(
            "No changes detected"
            if not package_labels
            else f"No changes detected in {'package' if len(package_labels) == 1 else 'packages'} "
            f"'{', '.join(package_labels)}'",
            level=1,
        )
    else:
        if check_changes:
            sys.exit(1)

        write_migration_files(changes)


@cli.command()
@click.argument("package_label", required=False)
@click.argument("migration_name", required=False)
@click.option(
    "--database",
    default=DEFAULT_DB_ALIAS,
    help="Nominates a database to synchronize. Defaults to the 'default' database.",
)
@click.option(
    "--fake", is_flag=True, help="Mark migrations as run without actually running them."
)
@click.option(
    "--fake-initial",
    is_flag=True,
    help="Detect if tables already exist and fake-apply initial migrations if so. Make sure that the current database schema matches your initial migration before using this flag. Plain will only check for an existing table name.",
)
@click.option(
    "--plan",
    is_flag=True,
    help="Shows a list of the migration actions that will be performed.",
)
@click.option(
    "--check",
    "check_unapplied",
    is_flag=True,
    help="Exits with a non-zero status if unapplied migrations exist and does not actually apply migrations.",
)
@click.option(
    "--backup/--no-backup",
    "backup",
    is_flag=True,
    default=None,
    help="Explicitly enable/disable pre-migration backups.",
)
@click.option(
    "--prune",
    is_flag=True,
    help="Delete nonexistent migrations from the plainmigrations table.",
)
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def migrate(
    package_label,
    migration_name,
    database,
    fake,
    fake_initial,
    plan,
    check_unapplied,
    backup,
    prune,
    verbosity,
):
    """Updates database schema. Manages both packages with migrations and those without."""

    def migration_progress_callback(action, migration=None, fake=False):
        if verbosity >= 1:
            compute_time = verbosity > 1
            if action == "apply_start":
                if compute_time:
                    start = time.monotonic()
                click.echo(f"  Applying {migration}...", nl=False)
            elif action == "apply_success":
                elapsed = f" ({time.monotonic() - start:.3f}s)" if compute_time else ""
                if fake:
                    click.echo(click.style(f" FAKED{elapsed}", fg="green"))
                else:
                    click.echo(click.style(f" OK{elapsed}", fg="green"))
            elif action == "render_start":
                if compute_time:
                    start = time.monotonic()
                click.echo("  Rendering model states...", nl=False)
            elif action == "render_success":
                elapsed = f" ({time.monotonic() - start:.3f}s)" if compute_time else ""
                click.echo(click.style(f" DONE{elapsed}", fg="green"))

    def describe_operation(operation):
        """Return a string that describes a migration operation for --plan."""
        prefix = ""
        is_error = False
        if hasattr(operation, "code"):
            code = operation.code
            action = (code.__doc__ or "") if code else None
        elif hasattr(operation, "sql"):
            action = operation.sql
        else:
            action = ""
        if action is not None:
            action = str(action).replace("\n", "")
        if action:
            action = " -> " + action
        truncated = Truncator(action)
        return prefix + operation.describe() + truncated.chars(40), is_error

    # Get the database we're operating from
    connection = connections[database]

    # Hook for backends needing any database preparation
    connection.prepare_database()

    # Work out which packages have migrations and which do not
    executor = MigrationExecutor(connection, migration_progress_callback)

    # Raise an error if any migrations are applied before their dependencies.
    executor.loader.check_consistent_history(connection)

    # Before anything else, see if there's conflicting packages and drop out
    # hard if there are any
    conflicts = executor.loader.detect_conflicts()
    if conflicts:
        name_str = "; ".join(
            "{} in {}".format(", ".join(names), package)
            for package, names in conflicts.items()
        )
        raise click.ClickException(
            "Conflicting migrations detected; multiple leaf nodes in the "
            f"migration graph: ({name_str}).\nTo fix them run "
            "'python manage.py makemigrations --merge'"
        )

    # If they supplied command line arguments, work out what they mean.
    target_package_labels_only = True
    if package_label:
        try:
            packages_registry.get_package_config(package_label)
        except LookupError as err:
            raise click.ClickException(str(err))

        if package_label not in executor.loader.migrated_packages:
            raise click.ClickException(
                f"Package '{package_label}' does not have migrations."
            )

    if package_label and migration_name:
        try:
            migration = executor.loader.get_migration_by_prefix(
                package_label, migration_name
            )
        except AmbiguityError:
            raise click.ClickException(
                f"More than one migration matches '{migration_name}' in package '{package_label}'. "
                "Please be more specific."
            )
        except KeyError:
            raise click.ClickException(
                f"Cannot find a migration matching '{migration_name}' from package '{package_label}'."
            )
        target = (package_label, migration.name)
        if (
            target not in executor.loader.graph.nodes
            and target in executor.loader.replacements
        ):
            incomplete_migration = executor.loader.replacements[target]
            target = incomplete_migration.replaces[-1]
        targets = [target]
        target_package_labels_only = False
    elif package_label:
        targets = [
            key for key in executor.loader.graph.leaf_nodes() if key[0] == package_label
        ]
    else:
        targets = executor.loader.graph.leaf_nodes()

    if prune:
        if not package_label:
            raise click.ClickException(
                "Migrations can be pruned only when a package is specified."
            )
        if verbosity > 0:
            click.echo("Pruning migrations:", color="cyan")
        to_prune = set(executor.loader.applied_migrations) - set(
            executor.loader.disk_migrations
        )
        squashed_migrations_with_deleted_replaced_migrations = [
            migration_key
            for migration_key, migration_obj in executor.loader.replacements.items()
            if any(replaced in to_prune for replaced in migration_obj.replaces)
        ]
        if squashed_migrations_with_deleted_replaced_migrations:
            click.echo(
                click.style(
                    "  Cannot use --prune because the following squashed "
                    "migrations have their 'replaces' attributes and may not "
                    "be recorded as applied:",
                    fg="yellow",
                )
            )
            for migration in squashed_migrations_with_deleted_replaced_migrations:
                package, name = migration
                click.echo(f"    {package}.{name}")
            click.echo(
                click.style(
                    "  Re-run 'manage.py migrate' if they are not marked as "
                    "applied, and remove 'replaces' attributes in their "
                    "Migration classes.",
                    fg="yellow",
                )
            )
        else:
            to_prune = sorted(
                migration for migration in to_prune if migration[0] == package_label
            )
            if to_prune:
                for migration in to_prune:
                    package, name = migration
                    if verbosity > 0:
                        click.echo(
                            click.style(f"  Pruning {package}.{name}", fg="yellow"),
                            nl=False,
                        )
                    executor.recorder.record_unapplied(package, name)
                    if verbosity > 0:
                        click.echo(click.style(" OK", fg="green"))
            elif verbosity > 0:
                click.echo("  No migrations to prune.")

    migration_plan = executor.migration_plan(targets)

    if plan:
        click.echo("Planned operations:", color="cyan")
        if not migration_plan:
            click.echo("  No planned migration operations.")
        else:
            for migration in migration_plan:
                click.echo(str(migration), color="cyan")
                for operation in migration.operations:
                    message, is_error = describe_operation(operation)
                    if is_error:
                        click.echo("    " + message, fg="yellow")
                    else:
                        click.echo("    " + message)
        if check_unapplied:
            sys.exit(1)
        return

    if check_unapplied:
        if migration_plan:
            sys.exit(1)
        return

    if prune:
        return

    # Print some useful info
    if verbosity >= 1:
        click.echo("Operations to perform:", color="cyan")

        if target_package_labels_only:
            click.echo(
                "  Apply all migrations: "
                + (", ".join(sorted({a for a, n in targets})) or "(none)"),
                color="yellow",
            )
        else:
            click.echo(
                f"  Target specific migration: {targets[0][1]}, from {targets[0][0]}",
                color="yellow",
            )

    pre_migrate_state = executor._create_project_state(with_applied_migrations=True)

    # sql = executor.loader.collect_sql(migration_plan)
    # pprint(sql)

    if migration_plan:
        if backup or (
            backup is None
            and settings.DEBUG
            and click.confirm(
                "\nYou are in DEBUG mode. Would you like to make a database backup before running migrations?"
            )
        ):
            backup_name = f"migrate_{time.strftime('%Y%m%d_%H%M%S')}"
            # Can't use ctx.invoke because this is called by the test db creation currently,
            # which doesn't have a context.
            create_backup.callback(
                backup_name=backup_name,
                pg_dump=os.environ.get(
                    "PG_DUMP", "pg_dump"
                ),  # Have to this again manually
            )
            print()

        if verbosity >= 1:
            click.echo("Running migrations:", color="cyan")

        post_migrate_state = executor.migrate(
            targets,
            plan=migration_plan,
            state=pre_migrate_state.clone(),
            fake=fake,
            fake_initial=fake_initial,
        )
        # post_migrate signals have access to all models. Ensure that all models
        # are reloaded in case any are delayed.
        post_migrate_state.clear_delayed_packages_cache()
        post_migrate_packages = post_migrate_state.models_registry

        # Re-render models of real packages to include relationships now that
        # we've got a final state. This wouldn't be necessary if real packages
        # models were rendered with relationships in the first place.
        with post_migrate_packages.bulk_update():
            model_keys = []
            for model_state in post_migrate_packages.real_models:
                model_key = model_state.package_label, model_state.name_lower
                model_keys.append(model_key)
                post_migrate_packages.unregister_model(*model_key)
        post_migrate_packages.render_multiple(
            [
                ModelState.from_model(models_registry.get_model(*model))
                for model in model_keys
            ]
        )

    elif verbosity >= 1:
        click.echo("  No migrations to apply.")
        # If there's changes that aren't in migrations yet, tell them
        # how to fix it.
        autodetector = MigrationAutodetector(
            executor.loader.project_state(),
            ProjectState.from_models_registry(models_registry),
        )
        changes = autodetector.changes(graph=executor.loader.graph)
        if changes:
            click.echo(
                click.style(
                    f"  Your models in package(s): {', '.join(repr(package) for package in sorted(changes))} "
                    "have changes that are not yet reflected in a migration, and so won't be applied.",
                    fg="yellow",
                )
            )
            click.echo(
                click.style(
                    "  Run 'manage.py makemigrations' to make new "
                    "migrations, and then re-run 'manage.py migrate' to "
                    "apply them.",
                    fg="yellow",
                )
            )


@cli.command()
@click.argument("package_label")
@click.argument("migration_name")
@click.option(
    "--check",
    is_flag=True,
    help="Exit with a non-zero status if the migration can be optimized.",
)
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def optimize_migration(package_label, migration_name, check, verbosity):
    """Optimizes the operations for the named migration."""
    try:
        packages_registry.get_package_config(package_label)
    except LookupError as err:
        raise click.ClickException(str(err))

    # Load the current graph state.
    loader = MigrationLoader(None)
    if package_label not in loader.migrated_packages:
        raise click.ClickException(
            f"Package '{package_label}' does not have migrations."
        )

    # Find a migration.
    try:
        migration = loader.get_migration_by_prefix(package_label, migration_name)
    except AmbiguityError:
        raise click.ClickException(
            f"More than one migration matches '{migration_name}' in package "
            f"'{package_label}'. Please be more specific."
        )
    except KeyError:
        raise click.ClickException(
            f"Cannot find a migration matching '{migration_name}' from package "
            f"'{package_label}'."
        )

    # Optimize the migration.
    optimizer = MigrationOptimizer()
    new_operations = optimizer.optimize(migration.operations, migration.package_label)
    if len(migration.operations) == len(new_operations):
        if verbosity > 0:
            click.echo("No optimizations possible.")
        return
    else:
        if verbosity > 0:
            click.echo(
                f"Optimizing from {len(migration.operations)} operations to {len(new_operations)} operations."
            )
        if check:
            sys.exit(1)

    # Set the new migration optimizations.
    migration.operations = new_operations

    # Write out the optimized migration file.
    writer = MigrationWriter(migration)
    migration_file_string = writer.as_string()
    if writer.needs_manual_porting:
        if migration.replaces:
            raise click.ClickException(
                "Migration will require manual porting but is already a squashed "
                "migration.\nTransition to a normal migration first."
            )
        # Make a new migration with those operations.
        subclass = type(
            "Migration",
            (migrations.Migration,),
            {
                "dependencies": migration.dependencies,
                "operations": new_operations,
                "replaces": [(migration.package_label, migration.name)],
            },
        )
        optimized_migration_name = f"{migration.name}_optimized"
        optimized_migration = subclass(optimized_migration_name, package_label)
        writer = MigrationWriter(optimized_migration)
        migration_file_string = writer.as_string()
        if verbosity > 0:
            click.echo(click.style("Manual porting required", fg="yellow", bold=True))
            click.echo(
                "  Your migrations contained functions that must be manually "
                "copied over,\n"
                "  as we could not safely copy their implementation.\n"
                "  See the comment at the top of the optimized migration for "
                "details."
            )

    with open(writer.path, "w", encoding="utf-8") as fh:
        fh.write(migration_file_string)

    if verbosity > 0:
        click.echo(
            click.style(f"Optimized migration {writer.path}", fg="green", bold=True)
        )


@cli.command()
@click.argument("package_labels", nargs=-1)
@click.option(
    "--database",
    default=DEFAULT_DB_ALIAS,
    help="Nominates a database to show migrations for. Defaults to the 'default' database.",
)
@click.option(
    "--format",
    type=click.Choice(["list", "plan"]),
    default="list",
    help="Output format.",
)
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def show_migrations(package_labels, database, format, verbosity):
    """Shows all available migrations for the current project"""

    def _validate_package_names(package_names):
        has_bad_names = False
        for package_name in package_names:
            try:
                packages_registry.get_package_config(package_name)
            except LookupError as err:
                click.echo(str(err), err=True)
                has_bad_names = True
        if has_bad_names:
            sys.exit(2)

    def show_list(connection, package_names):
        """
        Show a list of all migrations on the system, or only those of
        some named packages.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        recorder = MigrationRecorder(connection)
        recorded_migrations = recorder.applied_migrations()
        graph = loader.graph
        # If we were passed a list of packages, validate it
        if package_names:
            _validate_package_names(package_names)
        # Otherwise, show all packages in alphabetic order
        else:
            package_names = sorted(loader.migrated_packages)
        # For each app, print its migrations in order from oldest (roots) to
        # newest (leaves).
        for package_name in package_names:
            click.secho(package_name, fg="cyan", bold=True)
            shown = set()
            for node in graph.leaf_nodes(package_name):
                for plan_node in graph.forwards_plan(node):
                    if plan_node not in shown and plan_node[0] == package_name:
                        # Give it a nice title if it's a squashed one
                        title = plan_node[1]
                        if graph.nodes[plan_node].replaces:
                            title += f" ({len(graph.nodes[plan_node].replaces)} squashed migrations)"
                        applied_migration = loader.applied_migrations.get(plan_node)
                        # Mark it as applied/unapplied
                        if applied_migration:
                            if plan_node in recorded_migrations:
                                output = f" [X] {title}"
                            else:
                                title += " Run 'manage.py migrate' to finish recording."
                                output = f" [-] {title}"
                            if verbosity >= 2 and hasattr(applied_migration, "applied"):
                                output += f" (applied at {applied_migration.applied.strftime('%Y-%m-%d %H:%M:%S')})"
                            click.echo(output)
                        else:
                            click.echo(f" [ ] {title}")
                        shown.add(plan_node)
            # If we didn't print anything, then a small message
            if not shown:
                click.secho(" (no migrations)", fg="red")

    def show_plan(connection, package_names):
        """
        Show all known migrations (or only those of the specified package_names)
        in the order they will be applied.
        """
        # Load migrations from disk/DB
        loader = MigrationLoader(connection)
        graph = loader.graph
        if package_names:
            _validate_package_names(package_names)
            targets = [key for key in graph.leaf_nodes() if key[0] in package_names]
        else:
            targets = graph.leaf_nodes()
        plan = []
        seen = set()

        # Generate the plan
        for target in targets:
            for migration in graph.forwards_plan(target):
                if migration not in seen:
                    node = graph.node_map[migration]
                    plan.append(node)
                    seen.add(migration)

        # Output
        def print_deps(node):
            out = []
            for parent in sorted(node.parents):
                out.append(f"{parent.key[0]}.{parent.key[1]}")
            if out:
                return f" ... ({', '.join(out)})"
            return ""

        for node in plan:
            deps = ""
            if verbosity >= 2:
                deps = print_deps(node)
            if node.key in loader.applied_migrations:
                click.echo(f"[X]  {node.key[0]}.{node.key[1]}{deps}")
            else:
                click.echo(f"[ ]  {node.key[0]}.{node.key[1]}{deps}")
        if not plan:
            click.secho("(no migrations)", fg="red")

    # Get the database we're operating from
    connection = connections[database]

    if format == "plan":
        show_plan(connection, package_labels)
    else:
        show_list(connection, package_labels)


@cli.command()
@click.argument("package_label")
@click.argument("start_migration_name", required=False)
@click.argument("migration_name")
@click.option(
    "--no-optimize",
    is_flag=True,
    help="Do not try to optimize the squashed operations.",
)
@click.option(
    "--noinput",
    "--no-input",
    "no_input",
    is_flag=True,
    help="Tells Plain to NOT prompt the user for input of any kind.",
)
@click.option("--squashed-name", help="Sets the name of the new squashed migration.")
@click.option(
    "-v",
    "--verbosity",
    type=int,
    default=1,
    help="Verbosity level; 0=minimal output, 1=normal output, 2=verbose output, 3=very verbose output",
)
def squash_migrations(
    package_label,
    start_migration_name,
    migration_name,
    no_optimize,
    no_input,
    squashed_name,
    verbosity,
):
    """
    Squashes an existing set of migrations (from first until specified) into a single new one.
    """
    interactive = not no_input

    def find_migration(loader, package_label, name):
        try:
            return loader.get_migration_by_prefix(package_label, name)
        except AmbiguityError:
            raise click.ClickException(
                f"More than one migration matches '{name}' in package '{package_label}'. Please be more specific."
            )
        except KeyError:
            raise click.ClickException(
                f"Cannot find a migration matching '{name}' from package '{package_label}'."
            )

    # Validate package_label
    try:
        packages_registry.get_package_config(package_label)
    except LookupError as err:
        raise click.ClickException(str(err))

    # Load the current graph state, check the app and migration they asked for exists
    loader = MigrationLoader(connections[DEFAULT_DB_ALIAS])
    if package_label not in loader.migrated_packages:
        raise click.ClickException(
            f"Package '{package_label}' does not have migrations (so squashmigrations on it makes no sense)"
        )

    migration = find_migration(loader, package_label, migration_name)

    # Work out the list of predecessor migrations
    migrations_to_squash = [
        loader.get_migration(al, mn)
        for al, mn in loader.graph.forwards_plan(
            (migration.package_label, migration.name)
        )
        if al == migration.package_label
    ]

    if start_migration_name:
        start_migration = find_migration(loader, package_label, start_migration_name)
        start = loader.get_migration(
            start_migration.package_label, start_migration.name
        )
        try:
            start_index = migrations_to_squash.index(start)
            migrations_to_squash = migrations_to_squash[start_index:]
        except ValueError:
            raise click.ClickException(
                f"The migration '{start_migration}' cannot be found. Maybe it comes after "
                f"the migration '{migration}'?\n"
                f"Have a look at:\n"
                f"  python manage.py showmigrations {package_label}\n"
                f"to debug this issue."
            )

    # Tell them what we're doing and optionally ask if we should proceed
    if verbosity > 0 or interactive:
        click.secho("Will squash the following migrations:", fg="cyan", bold=True)
        for migration in migrations_to_squash:
            click.echo(f" - {migration.name}")

        if interactive:
            if not click.confirm("Do you wish to proceed?"):
                return

    # Load the operations from all those migrations and concat together,
    # along with collecting external dependencies and detecting double-squashing
    operations = []
    dependencies = set()
    # We need to take all dependencies from the first migration in the list
    # as it may be 0002 depending on 0001
    first_migration = True
    for smigration in migrations_to_squash:
        if smigration.replaces:
            raise click.ClickException(
                "You cannot squash squashed migrations! Please transition it to a "
                "normal migration first"
            )
        operations.extend(smigration.operations)
        for dependency in smigration.dependencies:
            if isinstance(dependency, SwappableTuple):
                if getattr(settings, "AUTH_USER_MODEL", None) == dependency.setting:
                    dependencies.add(("__setting__", "AUTH_USER_MODEL"))
                else:
                    dependencies.add(dependency)
            elif dependency[0] != smigration.package_label or first_migration:
                dependencies.add(dependency)
        first_migration = False

    if no_optimize:
        if verbosity > 0:
            click.secho("(Skipping optimization.)", fg="yellow")
        new_operations = operations
    else:
        if verbosity > 0:
            click.secho("Optimizing...", fg="cyan")

        optimizer = MigrationOptimizer()
        new_operations = optimizer.optimize(operations, migration.package_label)

        if verbosity > 0:
            if len(new_operations) == len(operations):
                click.echo("  No optimizations possible.")
            else:
                click.echo(
                    f"  Optimized from {len(operations)} operations to {len(new_operations)} operations."
                )

    # Work out the value of replaces (any squashed ones we're re-squashing)
    # need to feed their replaces into ours
    replaces = []
    for migration in migrations_to_squash:
        if migration.replaces:
            replaces.extend(migration.replaces)
        else:
            replaces.append((migration.package_label, migration.name))

    # Make a new migration with those operations
    subclass = type(
        "Migration",
        (migrations.Migration,),
        {
            "dependencies": dependencies,
            "operations": new_operations,
            "replaces": replaces,
        },
    )
    if start_migration_name:
        if squashed_name:
            # Use the name from --squashed-name
            prefix, _ = start_migration.name.split("_", 1)
            name = f"{prefix}_{squashed_name}"
        else:
            # Generate a name
            name = f"{start_migration.name}_squashed_{migration.name}"
        new_migration = subclass(name, package_label)
    else:
        name = f"0001_{'squashed_' + migration.name if not squashed_name else squashed_name}"
        new_migration = subclass(name, package_label)
        new_migration.initial = True

    # Write out the new migration file
    writer = MigrationWriter(new_migration)
    if os.path.exists(writer.path):
        raise click.ClickException(
            f"Migration {new_migration.name} already exists. Use a different name."
        )
    with open(writer.path, "w", encoding="utf-8") as fh:
        fh.write(writer.as_string())

    if verbosity > 0:
        click.secho(
            f"Created new squashed migration {writer.path}", fg="green", bold=True
        )
        click.echo(
            "  You should commit this migration but leave the old ones in place;\n"
            "  the new migration will be used for new installs. Once you are sure\n"
            "  all instances of the codebase have applied the migrations you squashed,\n"
            "  you can delete them."
        )
        if writer.needs_manual_porting:
            click.secho("Manual porting required", fg="yellow", bold=True)
            click.echo(
                "  Your migrations contained functions that must be manually copied over,\n"
                "  as we could not safely copy their implementation.\n"
                "  See the comment at the top of the squashed migration for details."
            )
