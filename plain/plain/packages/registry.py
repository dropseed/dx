import sys
import threading
from collections import Counter

from plain.exceptions import ImproperlyConfigured, PackageRegistryNotReady

from .config import PackageConfig


class PackagesRegistry:
    """
    A registry that stores the configuration of installed applications.

    It also keeps track of models, e.g. to provide reverse relations.
    """

    def __init__(self, installed_packages=()):
        # installed_packages is set to None when creating the main registry
        # because it cannot be populated at that point. Other registries must
        # provide a list of installed packages and are populated immediately.
        if installed_packages is None and hasattr(
            sys.modules[__name__], "packages_registry"
        ):
            raise RuntimeError("You must supply an installed_packages argument.")

        # Mapping of labels to PackageConfig instances for installed packages.
        self.package_configs = {}

        # Whether the registry is populated.
        self.packages_ready = self.ready = False

        # Lock for thread-safe population.
        self._lock = threading.RLock()
        self.loading = False

        # Populate packages and models, unless it's the main registry.
        if installed_packages is not None:
            self.populate(installed_packages)

    def populate(self, installed_packages=None):
        """
        Load application configurations and models.

        Import each application module and then each model module.

        It is thread-safe and idempotent, but not reentrant.
        """
        if self.ready:
            return

        # populate() might be called by two threads in parallel on servers
        # that create threads before initializing the WSGI callable.
        with self._lock:
            if self.ready:
                return

            # An RLock prevents other threads from entering this section. The
            # compare and set operation below is atomic.
            if self.loading:
                # Prevent reentrant calls to avoid running PackageConfig.ready()
                # methods twice.
                raise RuntimeError("populate() isn't reentrant")
            self.loading = True

            # Phase 1: initialize app configs and import app modules.
            for entry in installed_packages:
                if isinstance(entry, PackageConfig):
                    package_config = entry
                else:
                    package_config = PackageConfig.create(entry)
                if package_config.label in self.package_configs:
                    raise ImproperlyConfigured(
                        "Package labels aren't unique, "
                        f"duplicates: {package_config.label}"
                    )

                self.package_configs[package_config.label] = package_config
                package_config.packages_registry = self

            # Check for duplicate app names.
            counts = Counter(
                package_config.name for package_config in self.package_configs.values()
            )
            duplicates = [name for name, count in counts.most_common() if count > 1]
            if duplicates:
                raise ImproperlyConfigured(
                    "Package names aren't unique, duplicates: {}".format(
                        ", ".join(duplicates)
                    )
                )

            self.packages_ready = True

            # Phase 3: run ready() methods of app configs.
            for package_config in self.get_package_configs():
                package_config.ready()

            self.ready = True

    def check_packages_ready(self):
        """Raise an exception if all packages haven't been imported yet."""
        if not self.packages_ready:
            from plain.runtime import settings

            # If "not ready" is due to unconfigured settings, accessing
            # INSTALLED_PACKAGES raises a more helpful ImproperlyConfigured
            # exception.
            settings.INSTALLED_PACKAGES
            raise PackageRegistryNotReady("Packages aren't loaded yet.")

    def get_package_configs(self):
        """Import applications and return an iterable of app configs."""
        self.check_packages_ready()
        return self.package_configs.values()

    def get_package_config(self, package_label):
        """
        Import applications and returns an app config for the given label.

        Raise LookupError if no application exists with this label.
        """
        self.check_packages_ready()
        try:
            return self.package_configs[package_label]
        except KeyError:
            message = f"No installed app with label '{package_label}'."
            for package_config in self.get_package_configs():
                if package_config.name == package_label:
                    message += f" Did you mean '{package_config.label}'?"
                    break
            raise LookupError(message)

    def get_containing_package_config(self, object_name):
        """
        Look for an app config containing a given object.

        object_name is the dotted Python path to the object.

        Return the app config for the inner application in case of nesting.
        Return None if the object isn't in any registered app config.
        """
        self.check_packages_ready()
        candidates = []
        for package_config in self.package_configs.values():
            if object_name.startswith(package_config.name):
                subpath = object_name.removeprefix(package_config.name)
                if subpath == "" or subpath[0] == ".":
                    candidates.append(package_config)
        if candidates:
            return sorted(candidates, key=lambda ac: -len(ac.name))[0]


packages_registry = PackagesRegistry(installed_packages=None)
