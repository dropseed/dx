from plain import models
from plain.models.migrations.operations.base import Operation
from plain.models.migrations.state import ModelState
from plain.models.migrations.utils import field_references, resolve_relation
from plain.utils.functional import cached_property

from .fields import AddField, AlterField, FieldOperation, RemoveField, RenameField


def _check_for_duplicates(arg_name, objs):
    used_vals = set()
    for val in objs:
        if val in used_vals:
            raise ValueError(
                f"Found duplicate value {val} in CreateModel {arg_name} argument."
            )
        used_vals.add(val)


class ModelOperation(Operation):
    def __init__(self, name):
        self.name = name

    @cached_property
    def name_lower(self):
        return self.name.lower()

    def references_model(self, name, package_label):
        return name.lower() == self.name_lower

    def reduce(self, operation, package_label):
        return super().reduce(operation, package_label) or self.can_reduce_through(
            operation, package_label
        )

    def can_reduce_through(self, operation, package_label):
        return not operation.references_model(self.name, package_label)


class CreateModel(ModelOperation):
    """Create a model's table."""

    serialization_expand_args = ["fields", "options", "managers"]

    def __init__(self, name, fields, options=None, bases=None, managers=None):
        self.fields = fields
        self.options = options or {}
        self.bases = bases or (models.Model,)
        self.managers = managers or []
        super().__init__(name)
        # Sanity-check that there are no duplicated field names, bases, or
        # manager names
        _check_for_duplicates("fields", (name for name, _ in self.fields))
        _check_for_duplicates(
            "bases",
            (
                base._meta.label_lower
                if hasattr(base, "_meta")
                else base.lower()
                if isinstance(base, str)
                else base
                for base in self.bases
            ),
        )
        _check_for_duplicates("managers", (name for name, _ in self.managers))

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "fields": self.fields,
        }
        if self.options:
            kwargs["options"] = self.options
        if self.bases and self.bases != (models.Model,):
            kwargs["bases"] = self.bases
        if self.managers and self.managers != [("objects", models.Manager())]:
            kwargs["managers"] = self.managers
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.add_model(
            ModelState(
                package_label,
                self.name,
                list(self.fields),
                dict(self.options),
                tuple(self.bases),
                list(self.managers),
            )
        )

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = to_state.models_registry.get_model(package_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.create_model(model)

    def describe(self):
        return f"Create model {self.name}"

    @property
    def migration_name_fragment(self):
        return self.name_lower

    def references_model(self, name, package_label):
        name_lower = name.lower()
        if name_lower == self.name_lower:
            return True

        # Check we didn't inherit from the model
        reference_model_tuple = (package_label, name_lower)
        for base in self.bases:
            if (
                base is not models.Model
                and isinstance(base, models.base.ModelBase | str)
                and resolve_relation(base, package_label) == reference_model_tuple
            ):
                return True

        # Check we have no FKs/M2Ms with it
        for _name, field in self.fields:
            if field_references(
                (package_label, self.name_lower), field, reference_model_tuple
            ):
                return True
        return False

    def reduce(self, operation, package_label):
        if (
            isinstance(operation, DeleteModel)
            and self.name_lower == operation.name_lower
        ):
            return []
        elif (
            isinstance(operation, RenameModel)
            and self.name_lower == operation.old_name_lower
        ):
            return [
                CreateModel(
                    operation.new_name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterModelOptions)
            and self.name_lower == operation.name_lower
        ):
            options = {**self.options, **operation.options}
            for key in operation.ALTER_OPTION_KEYS:
                if key not in operation.options:
                    options.pop(key, None)
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options=options,
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterModelManagers)
            and self.name_lower == operation.name_lower
        ):
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options=self.options,
                    bases=self.bases,
                    managers=operation.managers,
                ),
            ]
        elif (
            isinstance(operation, AlterOrderWithRespectTo)
            and self.name_lower == operation.name_lower
        ):
            return [
                CreateModel(
                    self.name,
                    fields=self.fields,
                    options={
                        **self.options,
                        "order_with_respect_to": operation.order_with_respect_to,
                    },
                    bases=self.bases,
                    managers=self.managers,
                ),
            ]
        elif (
            isinstance(operation, FieldOperation)
            and self.name_lower == operation.model_name_lower
        ):
            if isinstance(operation, AddField):
                return [
                    CreateModel(
                        self.name,
                        fields=self.fields + [(operation.name, operation.field)],
                        options=self.options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, AlterField):
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (n, operation.field if n == operation.name else v)
                            for n, v in self.fields
                        ],
                        options=self.options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RemoveField):
                options = self.options.copy()

                order_with_respect_to = options.get("order_with_respect_to")
                if order_with_respect_to == operation.name_lower:
                    del options["order_with_respect_to"]
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (n, v)
                            for n, v in self.fields
                            if n.lower() != operation.name_lower
                        ],
                        options=options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
            elif isinstance(operation, RenameField):
                options = self.options.copy()

                order_with_respect_to = options.get("order_with_respect_to")
                if order_with_respect_to == operation.old_name:
                    options["order_with_respect_to"] = operation.new_name
                return [
                    CreateModel(
                        self.name,
                        fields=[
                            (operation.new_name if n == operation.old_name else n, v)
                            for n, v in self.fields
                        ],
                        options=options,
                        bases=self.bases,
                        managers=self.managers,
                    ),
                ]
        return super().reduce(operation, package_label)


class DeleteModel(ModelOperation):
    """Drop a model's table."""

    def deconstruct(self):
        kwargs = {
            "name": self.name,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.remove_model(package_label, self.name_lower)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = from_state.models_registry.get_model(package_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.delete_model(model)

    def references_model(self, name, package_label):
        # The deleted model could be referencing the specified model through
        # related fields.
        return True

    def describe(self):
        return f"Delete model {self.name}"

    @property
    def migration_name_fragment(self):
        return f"delete_{self.name_lower}"


class RenameModel(ModelOperation):
    """Rename a model."""

    def __init__(self, old_name, new_name):
        self.old_name = old_name
        self.new_name = new_name
        super().__init__(old_name)

    @cached_property
    def old_name_lower(self):
        return self.old_name.lower()

    @cached_property
    def new_name_lower(self):
        return self.new_name.lower()

    def deconstruct(self):
        kwargs = {
            "old_name": self.old_name,
            "new_name": self.new_name,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.rename_model(package_label, self.old_name, self.new_name)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        new_model = to_state.models_registry.get_model(package_label, self.new_name)
        if self.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_model = from_state.models_registry.get_model(
                package_label, self.old_name
            )
            # Move the main table
            schema_editor.alter_db_table(
                new_model,
                old_model._meta.db_table,
                new_model._meta.db_table,
            )
            # Alter the fields pointing to us
            for related_object in old_model._meta.related_objects:
                if related_object.related_model == old_model:
                    model = new_model
                    related_key = (package_label, self.new_name_lower)
                else:
                    model = related_object.related_model
                    related_key = (
                        related_object.related_model._meta.package_label,
                        related_object.related_model._meta.model_name,
                    )
                to_field = to_state.models_registry.get_model(
                    *related_key
                )._meta.get_field(related_object.field.name)
                schema_editor.alter_field(
                    model,
                    related_object.field,
                    to_field,
                )
            # Rename M2M fields whose name is based on this model's name.
            fields = zip(
                old_model._meta.local_many_to_many, new_model._meta.local_many_to_many
            )
            for old_field, new_field in fields:
                # Skip self-referential fields as these are renamed above.
                if (
                    new_field.model == new_field.related_model
                    or not new_field.remote_field.through._meta.auto_created
                ):
                    continue
                # Rename columns and the M2M table.
                schema_editor._alter_many_to_many(
                    new_model,
                    old_field,
                    new_field,
                    strict=False,
                )

    def references_model(self, name, package_label):
        return (
            name.lower() == self.old_name_lower or name.lower() == self.new_name_lower
        )

    def describe(self):
        return f"Rename model {self.old_name} to {self.new_name}"

    @property
    def migration_name_fragment(self):
        return f"rename_{self.old_name_lower}_{self.new_name_lower}"

    def reduce(self, operation, package_label):
        if (
            isinstance(operation, RenameModel)
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameModel(
                    self.old_name,
                    operation.new_name,
                ),
            ]
        # Skip `ModelOperation.reduce` as we want to run `references_model`
        # against self.new_name.
        return super(ModelOperation, self).reduce(
            operation, package_label
        ) or not operation.references_model(self.new_name, package_label)


class ModelOptionOperation(ModelOperation):
    def reduce(self, operation, package_label):
        if (
            isinstance(operation, self.__class__ | DeleteModel)
            and self.name_lower == operation.name_lower
        ):
            return [operation]
        return super().reduce(operation, package_label)


class AlterModelTable(ModelOptionOperation):
    """Rename a model's table."""

    def __init__(self, name, table):
        self.table = table
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "table": self.table,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.alter_model_options(
            package_label, self.name_lower, {"db_table": self.table}
        )

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        new_model = to_state.models_registry.get_model(package_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_model = from_state.models_registry.get_model(package_label, self.name)
            schema_editor.alter_db_table(
                new_model,
                old_model._meta.db_table,
                new_model._meta.db_table,
            )
            # Rename M2M fields whose name is based on this model's db_table
            for old_field, new_field in zip(
                old_model._meta.local_many_to_many, new_model._meta.local_many_to_many
            ):
                if new_field.remote_field.through._meta.auto_created:
                    schema_editor.alter_db_table(
                        new_field.remote_field.through,
                        old_field.remote_field.through._meta.db_table,
                        new_field.remote_field.through._meta.db_table,
                    )

    def describe(self):
        return "Rename table for {} to {}".format(
            self.name,
            self.table if self.table is not None else "(default)",
        )

    @property
    def migration_name_fragment(self):
        return f"alter_{self.name_lower}_table"


class AlterModelTableComment(ModelOptionOperation):
    def __init__(self, name, table_comment):
        self.table_comment = table_comment
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "table_comment": self.table_comment,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.alter_model_options(
            package_label, self.name_lower, {"db_table_comment": self.table_comment}
        )

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        new_model = to_state.models_registry.get_model(package_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_model = from_state.models_registry.get_model(package_label, self.name)
            schema_editor.alter_db_table_comment(
                new_model,
                old_model._meta.db_table_comment,
                new_model._meta.db_table_comment,
            )

    def describe(self):
        return f"Alter {self.name} table comment"

    @property
    def migration_name_fragment(self):
        return f"alter_{self.name_lower}_table_comment"


class AlterOrderWithRespectTo(ModelOptionOperation):
    """Represent a change with the order_with_respect_to option."""

    option_name = "order_with_respect_to"

    def __init__(self, name, order_with_respect_to):
        self.order_with_respect_to = order_with_respect_to
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "order_with_respect_to": self.order_with_respect_to,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.alter_model_options(
            package_label,
            self.name_lower,
            {self.option_name: self.order_with_respect_to},
        )

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        to_model = to_state.models_registry.get_model(package_label, self.name)
        if self.allow_migrate_model(schema_editor.connection.alias, to_model):
            from_model = from_state.models_registry.get_model(package_label, self.name)
            # Remove a field if we need to
            if (
                from_model._meta.order_with_respect_to
                and not to_model._meta.order_with_respect_to
            ):
                schema_editor.remove_field(
                    from_model, from_model._meta.get_field("_order")
                )
            # Add a field if we need to (altering the column is untouched as
            # it's likely a rename)
            elif (
                to_model._meta.order_with_respect_to
                and not from_model._meta.order_with_respect_to
            ):
                field = to_model._meta.get_field("_order")
                if not field.has_default():
                    field.default = 0
                schema_editor.add_field(
                    from_model,
                    field,
                )

    def references_field(self, model_name, name, package_label):
        return self.references_model(model_name, package_label) and (
            self.order_with_respect_to is None or name == self.order_with_respect_to
        )

    def describe(self):
        return (
            f"Set order_with_respect_to on {self.name} to {self.order_with_respect_to}"
        )

    @property
    def migration_name_fragment(self):
        return f"alter_{self.name_lower}_order_with_respect_to"


class AlterModelOptions(ModelOptionOperation):
    """
    Set new model options that don't directly affect the database schema
    (like ordering). Python code in migrations
    may still need them.
    """

    # Model options we want to compare and preserve in an AlterModelOptions op
    ALTER_OPTION_KEYS = [
        "base_manager_name",
        "default_manager_name",
        "default_related_name",
        "get_latest_by",
        "managed",
        "ordering",
        "select_on_save",
    ]

    def __init__(self, name, options):
        self.options = options
        super().__init__(name)

    def deconstruct(self):
        kwargs = {
            "name": self.name,
            "options": self.options,
        }
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        state.alter_model_options(
            package_label,
            self.name_lower,
            self.options,
            self.ALTER_OPTION_KEYS,
        )

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        pass

    def describe(self):
        return f"Change Meta options on {self.name}"

    @property
    def migration_name_fragment(self):
        return f"alter_{self.name_lower}_options"


class AlterModelManagers(ModelOptionOperation):
    """Alter the model's managers."""

    serialization_expand_args = ["managers"]

    def __init__(self, name, managers):
        self.managers = managers
        super().__init__(name)

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.name, self.managers], {})

    def state_forwards(self, package_label, state):
        state.alter_model_managers(package_label, self.name_lower, self.managers)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        pass

    def describe(self):
        return f"Change managers on {self.name}"

    @property
    def migration_name_fragment(self):
        return f"alter_{self.name_lower}_managers"


class IndexOperation(Operation):
    option_name = "indexes"

    @cached_property
    def model_name_lower(self):
        return self.model_name.lower()


class AddIndex(IndexOperation):
    """Add an index on a model."""

    def __init__(self, model_name, index):
        self.model_name = model_name
        if not index.name:
            raise ValueError(
                "Indexes passed to AddIndex operations require a name "
                f"argument. {index!r} doesn't have one."
            )
        self.index = index

    def state_forwards(self, package_label, state):
        state.add_index(package_label, self.model_name_lower, self.index)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = to_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.add_index(model, self.index)

    def deconstruct(self):
        kwargs = {
            "model_name": self.model_name,
            "index": self.index,
        }
        return (
            self.__class__.__qualname__,
            [],
            kwargs,
        )

    def describe(self):
        if self.index.expressions:
            return "Create index {} on {} on model {}".format(
                self.index.name,
                ", ".join([str(expression) for expression in self.index.expressions]),
                self.model_name,
            )
        return "Create index {} on field(s) {} of model {}".format(
            self.index.name,
            ", ".join(self.index.fields),
            self.model_name,
        )

    @property
    def migration_name_fragment(self):
        return f"{self.model_name_lower}_{self.index.name.lower()}"


class RemoveIndex(IndexOperation):
    """Remove an index from a model."""

    def __init__(self, model_name, name):
        self.model_name = model_name
        self.name = name

    def state_forwards(self, package_label, state):
        state.remove_index(package_label, self.model_name_lower, self.name)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = from_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            from_model_state = from_state.models[package_label, self.model_name_lower]
            index = from_model_state.get_index_by_name(self.name)
            schema_editor.remove_index(model, index)

    def deconstruct(self):
        kwargs = {
            "model_name": self.model_name,
            "name": self.name,
        }
        return (
            self.__class__.__qualname__,
            [],
            kwargs,
        )

    def describe(self):
        return f"Remove index {self.name} from {self.model_name}"

    @property
    def migration_name_fragment(self):
        return f"remove_{self.model_name_lower}_{self.name.lower()}"


class RenameIndex(IndexOperation):
    """Rename an index."""

    def __init__(self, model_name, new_name, old_name=None, old_fields=None):
        if not old_name and not old_fields:
            raise ValueError(
                "RenameIndex requires one of old_name and old_fields arguments to be "
                "set."
            )
        if old_name and old_fields:
            raise ValueError(
                "RenameIndex.old_name and old_fields are mutually exclusive."
            )
        self.model_name = model_name
        self.new_name = new_name
        self.old_name = old_name
        self.old_fields = old_fields

    @cached_property
    def old_name_lower(self):
        return self.old_name.lower()

    @cached_property
    def new_name_lower(self):
        return self.new_name.lower()

    def deconstruct(self):
        kwargs = {
            "model_name": self.model_name,
            "new_name": self.new_name,
        }
        if self.old_name:
            kwargs["old_name"] = self.old_name
        if self.old_fields:
            kwargs["old_fields"] = self.old_fields
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label, state):
        if self.old_fields:
            state.add_index(
                package_label,
                self.model_name_lower,
                models.Index(fields=self.old_fields, name=self.new_name),
            )
        else:
            state.rename_index(
                package_label, self.model_name_lower, self.old_name, self.new_name
            )

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = to_state.models_registry.get_model(package_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return

        if self.old_fields:
            from_model = from_state.models_registry.get_model(
                package_label, self.model_name
            )
            columns = [
                from_model._meta.get_field(field).column for field in self.old_fields
            ]
            matching_index_name = schema_editor._constraint_names(
                from_model, column_names=columns, index=True
            )
            if len(matching_index_name) != 1:
                raise ValueError(
                    "Found wrong number ({}) of indexes for {}({}).".format(
                        len(matching_index_name),
                        from_model._meta.db_table,
                        ", ".join(columns),
                    )
                )
            old_index = models.Index(
                fields=self.old_fields,
                name=matching_index_name[0],
            )
        else:
            from_model_state = from_state.models[package_label, self.model_name_lower]
            old_index = from_model_state.get_index_by_name(self.old_name)
        # Don't alter when the index name is not changed.
        if old_index.name == self.new_name:
            return

        to_model_state = to_state.models[package_label, self.model_name_lower]
        new_index = to_model_state.get_index_by_name(self.new_name)
        schema_editor.rename_index(model, old_index, new_index)

    def describe(self):
        if self.old_name:
            return (
                f"Rename index {self.old_name} on {self.model_name} to {self.new_name}"
            )
        return (
            f"Rename unnamed index for {self.old_fields} on {self.model_name} to "
            f"{self.new_name}"
        )

    @property
    def migration_name_fragment(self):
        if self.old_name:
            return f"rename_{self.old_name_lower}_{self.new_name_lower}"
        return "rename_{}_{}_{}".format(
            self.model_name_lower,
            "_".join(self.old_fields),
            self.new_name_lower,
        )

    def reduce(self, operation, package_label):
        if (
            isinstance(operation, RenameIndex)
            and self.model_name_lower == operation.model_name_lower
            and operation.old_name
            and self.new_name_lower == operation.old_name_lower
        ):
            return [
                RenameIndex(
                    self.model_name,
                    new_name=operation.new_name,
                    old_name=self.old_name,
                    old_fields=self.old_fields,
                )
            ]
        return super().reduce(operation, package_label)


class AddConstraint(IndexOperation):
    option_name = "constraints"

    def __init__(self, model_name, constraint):
        self.model_name = model_name
        self.constraint = constraint

    def state_forwards(self, package_label, state):
        state.add_constraint(package_label, self.model_name_lower, self.constraint)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = to_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            schema_editor.add_constraint(model, self.constraint)

    def deconstruct(self):
        return (
            self.__class__.__name__,
            [],
            {
                "model_name": self.model_name,
                "constraint": self.constraint,
            },
        )

    def describe(self):
        return f"Create constraint {self.constraint.name} on model {self.model_name}"

    @property
    def migration_name_fragment(self):
        return f"{self.model_name_lower}_{self.constraint.name.lower()}"


class RemoveConstraint(IndexOperation):
    option_name = "constraints"

    def __init__(self, model_name, name):
        self.model_name = model_name
        self.name = name

    def state_forwards(self, package_label, state):
        state.remove_constraint(package_label, self.model_name_lower, self.name)

    def database_forwards(self, package_label, schema_editor, from_state, to_state):
        model = to_state.models_registry.get_model(package_label, self.model_name)
        if self.allow_migrate_model(schema_editor.connection.alias, model):
            from_model_state = from_state.models[package_label, self.model_name_lower]
            constraint = from_model_state.get_constraint_by_name(self.name)
            schema_editor.remove_constraint(model, constraint)

    def deconstruct(self):
        return (
            self.__class__.__name__,
            [],
            {
                "model_name": self.model_name,
                "name": self.name,
            },
        )

    def describe(self):
        return f"Remove constraint {self.name} from model {self.model_name}"

    @property
    def migration_name_fragment(self):
        return f"remove_{self.model_name_lower}_{self.name.lower()}"
