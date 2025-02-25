from importlib import import_module
from importlib.util import find_spec

from plain.packages import PackageConfig, packages_registry, register_config

from .registry import jobs_registry

JOBS_MODULE_NAME = "jobs"


@register_config
class Config(PackageConfig):
    label = "plainworker"

    def ready(self):
        # Trigger register calls to fire by importing the modules
        for package_config in packages_registry.get_package_configs():
            module_name = f"{package_config.name}.{JOBS_MODULE_NAME}"
            if find_spec(module_name):
                import_module(module_name)

        jobs_registry.ready = True
