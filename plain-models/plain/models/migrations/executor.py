from plain.models import migrations
from plain.models import models_registry as global_models
from plain.models.db import router

from .loader import MigrationLoader
from .recorder import MigrationRecorder
from .state import ProjectState


class MigrationExecutor:
    """
    End-to-end migration execution - load migrations and run them up or down
    to a specified set of targets.
    """

    def __init__(self, connection, progress_callback=None):
        self.connection = connection
        self.loader = MigrationLoader(self.connection)
        self.recorder = MigrationRecorder(self.connection)
        self.progress_callback = progress_callback

    def migration_plan(self, targets, clean_start=False):
        """
        Given a set of targets, return a list of Migration instances.
        """
        plan = []
        if clean_start:
            applied = {}
        else:
            applied = dict(self.loader.applied_migrations)
        for target in targets:
            for migration in self.loader.graph.forwards_plan(target):
                if migration not in applied:
                    plan.append(self.loader.graph.nodes[migration])
                    applied[migration] = self.loader.graph.nodes[migration]
        return plan

    def _create_project_state(self, with_applied_migrations=False):
        """
        Create a project state including all the applications without
        migrations and applied migrations if with_applied_migrations=True.
        """
        state = ProjectState(real_packages=self.loader.unmigrated_packages)
        if with_applied_migrations:
            # Create the forwards plan Plain would follow on an empty database
            full_plan = self.migration_plan(
                self.loader.graph.leaf_nodes(), clean_start=True
            )
            applied_migrations = {
                self.loader.graph.nodes[key]
                for key in self.loader.applied_migrations
                if key in self.loader.graph.nodes
            }
            for migration in full_plan:
                if migration in applied_migrations:
                    migration.mutate_state(state, preserve=False)
        return state

    def migrate(self, targets, plan=None, state=None, fake=False, fake_initial=False):
        """
        Migrate the database up to the given targets.

        Plain first needs to create all project states before a migration is
        (un)applied and in a second step run all the database operations.
        """
        # The plain_migrations table must be present to record applied
        # migrations, but don't create it if there are no migrations to apply.
        if plan == []:
            if not self.recorder.has_table():
                return self._create_project_state(with_applied_migrations=False)
        else:
            self.recorder.ensure_schema()

        if plan is None:
            plan = self.migration_plan(targets)
        # Create the forwards plan Plain would follow on an empty database
        full_plan = self.migration_plan(
            self.loader.graph.leaf_nodes(), clean_start=True
        )

        if not plan:
            if state is None:
                # The resulting state should include applied migrations.
                state = self._create_project_state(with_applied_migrations=True)
        else:
            if state is None:
                # The resulting state should still include applied migrations.
                state = self._create_project_state(with_applied_migrations=True)
            state = self._migrate_all_forwards(
                state, plan, full_plan, fake=fake, fake_initial=fake_initial
            )

        self.check_replacements()

        return state

    def _migrate_all_forwards(self, state, plan, full_plan, fake, fake_initial):
        """
        Take a list of 2-tuples of the form (migration instance, False) and
        apply them in the order they occur in the full_plan.
        """
        migrations_to_run = set(plan)
        for migration in full_plan:
            if not migrations_to_run:
                # We remove every migration that we applied from these sets so
                # that we can bail out once the last migration has been applied
                # and don't always run until the very end of the migration
                # process.
                break
            if migration in migrations_to_run:
                if "models_registry" not in state.__dict__:
                    if self.progress_callback:
                        self.progress_callback("render_start")
                    state.models_registry  # Render all -- performance critical
                    if self.progress_callback:
                        self.progress_callback("render_success")
                state = self.apply_migration(
                    state, migration, fake=fake, fake_initial=fake_initial
                )
                migrations_to_run.remove(migration)

        return state

    def apply_migration(self, state, migration, fake=False, fake_initial=False):
        """Run a migration forwards."""
        migration_recorded = False
        if self.progress_callback:
            self.progress_callback("apply_start", migration, fake)
        if not fake:
            if fake_initial:
                # Test to see if this is an already-applied initial migration
                applied, state = self.detect_soft_applied(state, migration)
                if applied:
                    fake = True
            if not fake:
                # Alright, do it normally
                with self.connection.schema_editor(
                    atomic=migration.atomic
                ) as schema_editor:
                    state = migration.apply(state, schema_editor)
                    if not schema_editor.deferred_sql:
                        self.record_migration(migration)
                        migration_recorded = True
        if not migration_recorded:
            self.record_migration(migration)
        # Report progress
        if self.progress_callback:
            self.progress_callback("apply_success", migration, fake)
        return state

    def record_migration(self, migration):
        # For replacement migrations, record individual statuses
        if migration.replaces:
            for package_label, name in migration.replaces:
                self.recorder.record_applied(package_label, name)
        else:
            self.recorder.record_applied(migration.package_label, migration.name)

    def check_replacements(self):
        """
        Mark replacement migrations applied if their replaced set all are.

        Do this unconditionally on every migrate, rather than just when
        migrations are applied or unapplied, to correctly handle the case
        when a new squash migration is pushed to a deployment that already had
        all its replaced migrations applied. In this case no new migration will
        be applied, but the applied state of the squashed migration must be
        maintained.
        """
        applied = self.recorder.applied_migrations()
        for key, migration in self.loader.replacements.items():
            all_applied = all(m in applied for m in migration.replaces)
            if all_applied and key not in applied:
                self.recorder.record_applied(*key)

    def detect_soft_applied(self, project_state, migration):
        """
        Test whether a migration has been implicitly applied - that the
        tables or columns it would create exist. This is intended only for use
        on initial migrations (as it only looks for CreateModel and AddField).
        """

        def should_skip_detecting_model(migration, model):
            """
            No need to detect tables for unmanaged models, or
            models that can't be migrated on the current database.
            """
            return not model._meta.managed or not router.allow_migrate(
                self.connection.alias,
                migration.package_label,
                model_name=model._meta.model_name,
            )

        if migration.initial is None:
            # Bail if the migration isn't the first one in its app
            if any(
                app == migration.package_label for app, name in migration.dependencies
            ):
                return False, project_state
        elif migration.initial is False:
            # Bail if it's NOT an initial migration
            return False, project_state

        if project_state is None:
            after_state = self.loader.project_state(
                (migration.package_label, migration.name), at_end=True
            )
        else:
            after_state = migration.mutate_state(project_state)
        models_registry = after_state.models_registry
        found_create_model_migration = False
        found_add_field_migration = False
        fold_identifier_case = self.connection.features.ignores_table_name_case
        with self.connection.cursor() as cursor:
            existing_table_names = set(
                self.connection.introspection.table_names(cursor)
            )
            if fold_identifier_case:
                existing_table_names = {
                    name.casefold() for name in existing_table_names
                }
        # Make sure all create model and add field operations are done
        for operation in migration.operations:
            if isinstance(operation, migrations.CreateModel):
                model = models_registry.get_model(
                    migration.package_label, operation.name
                )
                if model._meta.swapped:
                    # We have to fetch the model to test with from the
                    # main app cache, as it's not a direct dependency.
                    model = global_models.get_model(model._meta.swapped)
                if should_skip_detecting_model(migration, model):
                    continue
                db_table = model._meta.db_table
                if fold_identifier_case:
                    db_table = db_table.casefold()
                if db_table not in existing_table_names:
                    return False, project_state
                found_create_model_migration = True
            elif isinstance(operation, migrations.AddField):
                model = models_registry.get_model(
                    migration.package_label, operation.model_name
                )
                if model._meta.swapped:
                    # We have to fetch the model to test with from the
                    # main app cache, as it's not a direct dependency.
                    model = global_models.get_model(model._meta.swapped)
                if should_skip_detecting_model(migration, model):
                    continue

                table = model._meta.db_table
                field = model._meta.get_field(operation.name)

                # Handle implicit many-to-many tables created by AddField.
                if field.many_to_many:
                    through_db_table = field.remote_field.through._meta.db_table
                    if fold_identifier_case:
                        through_db_table = through_db_table.casefold()
                    if through_db_table not in existing_table_names:
                        return False, project_state
                    else:
                        found_add_field_migration = True
                        continue
                with self.connection.cursor() as cursor:
                    columns = self.connection.introspection.get_table_description(
                        cursor, table
                    )
                for column in columns:
                    field_column = field.column
                    column_name = column.name
                    if fold_identifier_case:
                        column_name = column_name.casefold()
                        field_column = field_column.casefold()
                    if column_name == field_column:
                        found_add_field_migration = True
                        break
                else:
                    return False, project_state
        # If we get this far and we found at least one CreateModel or AddField
        # migration, the migration is considered implicitly applied.
        return (found_create_model_migration or found_add_field_migration), after_state
