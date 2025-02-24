import os

from plain.packages import PackageConfig, packages_registry, register_config
from plain.runtime import APP_PATH

from .registry import registry


@register_config
class Config(PackageConfig):
    def ready(self):
        for pacakge_config in packages_registry.get_package_configs():
            registry.discover_pages(
                os.path.join(pacakge_config.path, "templates", "pages")
            )

        registry.discover_pages(os.path.join(APP_PATH, "templates", "pages"))
