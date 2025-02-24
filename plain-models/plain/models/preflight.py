import inspect
from collections import defaultdict
from itertools import chain

from plain.models.registry import models_registry
from plain.packages import packages_registry
from plain.preflight import Error, Warning, register
from plain.runtime import settings


@register
def check_database_backends(databases=None, **kwargs):
    if databases is None:
        return []

    from plain.models.db import connections

    issues = []
    for alias in databases:
        conn = connections[alias]
        issues.extend(conn.validation.check(**kwargs))
    return issues


@register
def check_all_models(package_configs=None, **kwargs):
    db_table_models = defaultdict(list)
    indexes = defaultdict(list)
    constraints = defaultdict(list)
    errors = []
    if package_configs is None:
        models = models_registry.get_models()
    else:
        models = chain.from_iterable(
            models_registry.get_models(package_label=package_config.label)
            for package_config in package_configs
        )
    for model in models:
        if model._meta.managed:
            db_table_models[model._meta.db_table].append(model._meta.label)
        if not inspect.ismethod(model.check):
            errors.append(
                Error(
                    f"The '{model.__name__}.check()' class method is currently overridden by {model.check!r}.",
                    obj=model,
                    id="models.E020",
                )
            )
        else:
            errors.extend(model.check(**kwargs))
        for model_index in model._meta.indexes:
            indexes[model_index.name].append(model._meta.label)
        for model_constraint in model._meta.constraints:
            constraints[model_constraint.name].append(model._meta.label)
    if settings.DATABASE_ROUTERS:
        error_class, error_id = Warning, "models.W035"
        error_hint = (
            "You have configured settings.DATABASE_ROUTERS. Verify that %s "
            "are correctly routed to separate databases."
        )
    else:
        error_class, error_id = Error, "models.E028"
        error_hint = None
    for db_table, model_labels in db_table_models.items():
        if len(model_labels) != 1:
            model_labels_str = ", ".join(model_labels)
            errors.append(
                error_class(
                    f"db_table '{db_table}' is used by multiple models: {model_labels_str}.",
                    obj=db_table,
                    hint=(error_hint % model_labels_str) if error_hint else None,
                    id=error_id,
                )
            )
    for index_name, model_labels in indexes.items():
        if len(model_labels) > 1:
            model_labels = set(model_labels)
            errors.append(
                Error(
                    "index name '{}' is not unique {} {}.".format(
                        index_name,
                        "for model" if len(model_labels) == 1 else "among models:",
                        ", ".join(sorted(model_labels)),
                    ),
                    id="models.E029" if len(model_labels) == 1 else "models.E030",
                ),
            )
    for constraint_name, model_labels in constraints.items():
        if len(model_labels) > 1:
            model_labels = set(model_labels)
            errors.append(
                Error(
                    "constraint name '{}' is not unique {} {}.".format(
                        constraint_name,
                        "for model" if len(model_labels) == 1 else "among models:",
                        ", ".join(sorted(model_labels)),
                    ),
                    id="models.E031" if len(model_labels) == 1 else "models.E032",
                ),
            )
    return errors


def _check_lazy_references(models_registry, packages_registry, ignore=None):
    """
    Ensure all lazy (i.e. string) model references have been resolved.

    Lazy references are used in various places throughout Plain, primarily in
    related fields and model signals. Identify those common cases and provide
    more helpful error messages for them.

    The ignore parameter is used by StatePackages to exclude swappable models from
    this check.
    """
    pending_models = set(models_registry._pending_operations) - (ignore or set())

    # Short circuit if there aren't any errors.
    if not pending_models:
        return []

    def extract_operation(obj):
        """
        Take a callable found in Packages._pending_operations and identify the
        original callable passed to Packages.lazy_model_operation(). If that
        callable was a partial, return the inner, non-partial function and
        any arguments and keyword arguments that were supplied with it.

        obj is a callback defined locally in Packages.lazy_model_operation() and
        annotated there with a `func` attribute so as to imitate a partial.
        """
        operation, args, keywords = obj, [], {}
        while hasattr(operation, "func"):
            args.extend(getattr(operation, "args", []))
            keywords.update(getattr(operation, "keywords", {}))
            operation = operation.func
        return operation, args, keywords

    def app_model_error(model_key):
        try:
            packages_registry.get_package_config(model_key[0])
            model_error = "app '{}' doesn't provide model '{}'".format(*model_key)
        except LookupError:
            model_error = f"app '{model_key[0]}' isn't installed"
        return model_error

    # Here are several functions which return CheckMessage instances for the
    # most common usages of lazy operations throughout Plain. These functions
    # take the model that was being waited on as an (package_label, modelname)
    # pair, the original lazy function, and its positional and keyword args as
    # determined by extract_operation().

    def field_error(model_key, func, args, keywords):
        error_msg = (
            "The field %(field)s was declared with a lazy reference "
            "to '%(model)s', but %(model_error)s."
        )
        params = {
            "model": ".".join(model_key),
            "field": keywords["field"],
            "model_error": app_model_error(model_key),
        }
        return Error(error_msg % params, obj=keywords["field"], id="fields.E307")

    def default_error(model_key, func, args, keywords):
        error_msg = (
            "%(op)s contains a lazy reference to %(model)s, but %(model_error)s."
        )
        params = {
            "op": func,
            "model": ".".join(model_key),
            "model_error": app_model_error(model_key),
        }
        return Error(error_msg % params, obj=func, id="models.E022")

    # Maps common uses of lazy operations to corresponding error functions
    # defined above. If a key maps to None, no error will be produced.
    # default_error() will be used for usages that don't appear in this dict.
    known_lazy = {
        ("plain.models.fields.related", "resolve_related_class"): field_error,
        ("plain.models.fields.related", "set_managed"): None,
    }

    def build_error(model_key, func, args, keywords):
        key = (func.__module__, func.__name__)
        error_fn = known_lazy.get(key, default_error)
        return error_fn(model_key, func, args, keywords) if error_fn else None

    return sorted(
        filter(
            None,
            (
                build_error(model_key, *extract_operation(func))
                for model_key in pending_models
                for func in models_registry._pending_operations[model_key]
            ),
        ),
        key=lambda error: error.msg,
    )


@register
def check_lazy_references(package_configs=None, **kwargs):
    return _check_lazy_references(models_registry, packages_registry)


@register
def check_database_tables(package_configs, **kwargs):
    from plain.models.db import connection

    databases = kwargs.get("databases", None)
    if not databases:
        return []

    errors = []

    for database in databases:
        db_tables = connection.introspection.table_names()
        model_tables = connection.introspection.plain_table_names()

        unknown_tables = set(db_tables) - set(model_tables)
        unknown_tables.discard("plainmigrations")  # Know this could be there
        if unknown_tables:
            table_names = ", ".join(unknown_tables)
            specific_hint = f'echo "DROP TABLE IF EXISTS {unknown_tables.pop()}" | plain models db-shell'
            errors.append(
                Warning(
                    f"Unknown tables in {database} database: {table_names}",
                    hint=(
                        "Tables may be from packages/models that have been uninstalled. "
                        "Make sure you have a backup and delete the tables manually "
                        f"(ex. `{specific_hint}`)."
                    ),
                    id="plain.models.W001",
                )
            )

    return errors
