from importlib import import_module

from plain.packages import packages_registry
from plain.runtime import settings
from plain.utils.functional import LazyObject
from plain.utils.module_loading import import_string

from .environments import DefaultEnvironment, get_template_dirs


class JinjaEnvironment(LazyObject):
    def __init__(self, *args, **kwargs):
        self.__dict__["_imported_modules"] = set()
        super().__init__(*args, **kwargs)

    def _setup(self):
        environment_setting = settings.TEMPLATES_JINJA_ENVIRONMENT

        if isinstance(environment_setting, str):
            env = import_string(environment_setting)()
        else:
            env = environment_setting()

        # We have to set _wrapped before we trigger the autoloading of "register" commands
        self._wrapped = env

        for package_config in packages_registry.get_package_configs():
            # Allow this to fail in case there are import errors inside of their file
            import_name = f"{package_config.name}.templates"
            if import_name in self._imported_modules:
                continue
            try:
                import_module(import_name)
                self._imported_modules.add(import_name)
            except ModuleNotFoundError:
                pass

        # Allow this to fail in case there are import errors inside of their file
        import_name = "app.templates"
        if import_name not in self._imported_modules:
            try:
                import_module(import_name)
                self._imported_modules.add(import_name)
            except ModuleNotFoundError:
                pass


environment = JinjaEnvironment()


def register_template_extension(extension_class):
    environment.add_extension(extension_class)
    return extension_class


def register_template_global(value, name=None):
    """
    Adds a global to the Jinja environment.

    Can be used as a decorator on a function:

            @register_template_global
            def my_global():
                return "Hello, world!"

    Or as a function:

            register_template_global("Hello, world!", name="my_global")
    """
    if callable(value):
        environment.globals[name or value.__name__] = value
    elif name:
        environment.globals[name] = value
    else:
        raise ValueError("name must be provided if value is not callable")

    return value


def register_template_filter(func, name=None):
    """Adds a filter to the Jinja environment."""
    environment.filters[name or func.__name__] = func
    return func


__all__ = [
    "environment",
    "DefaultEnvironment",
    "get_template_dirs",
    "register_template_extension",
    "register_template_filter",
    "register_template_global",
]
