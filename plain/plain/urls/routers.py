import re
from types import ModuleType
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured

from .patterns import RegexPattern, RoutePattern, URLPattern
from .resolvers import (
    URLResolver,
)

if TYPE_CHECKING:
    from plain.views import View


class RouterBase:
    """
    Base class for defining url patterns.

    A namespace is required, and generally recommended,
    except for the root router in app.urls where it is typically "".
    """

    namespace: str
    urls: list


class RoutersRegistry:
    """Keep track of all the Routers that are explicitly registered in packages."""

    def __init__(self):
        self._routers = {}

    def register_router(self, router_class):
        router = (
            router_class()
        )  # Don't necessarily need to instantiate it yet, but will likely add methods.
        router_module_name = router_class.__module__
        self._routers[router_module_name] = router
        return router

    def get_module_router(self, module):
        if isinstance(module, str):
            module_name = module
        else:
            module_name = module.__name__

        try:
            return self._routers[module_name]
        except KeyError as e:
            registered_routers = ", ".join(self._routers.keys()) or "None"
            raise ImproperlyConfigured(
                f"Router {module_name} is not registered with the resolver. Use @register_router on the Router class in urls.py.\n\nRegistered routers: {registered_routers}"
            ) from e


def include(
    route: str | re.Pattern, module_or_urls: list | tuple | str | ModuleType
) -> URLResolver:
    """
    Include URLs from another module or a nested list of URL patterns.
    """
    if isinstance(route, str):
        pattern = RoutePattern(route, is_endpoint=False)
    elif isinstance(route, re.Pattern):
        pattern = RegexPattern(route.pattern, is_endpoint=False)
    else:
        raise TypeError("include() route must be a string or regex")

    if isinstance(module_or_urls, list | tuple):
        # We were given an explicit list of sub-patterns,
        # so we generate a router for it
        class _IncludeRouter(RouterBase):
            namespace = ""
            urls = module_or_urls

        return URLResolver(pattern=pattern, router=_IncludeRouter())
    else:
        # We were given a module, so we need to look up the router for that module
        module = module_or_urls
        router = routers_registry.get_module_router(module)

        return URLResolver(
            pattern=pattern,
            router=router,
        )


def path(route: str | re.Pattern, view: "View", *, name: str = "") -> URLPattern:
    """
    Standard URL with a view.
    """
    from plain.views import View

    if isinstance(route, str):
        pattern = RoutePattern(route, name=name, is_endpoint=True)
    elif isinstance(route, re.Pattern):
        pattern = RegexPattern(route.pattern, name=name, is_endpoint=True)
    else:
        raise TypeError("path() route must be a string or regex")

    # You can't pass a View() instance to path()
    if isinstance(view, View):
        view_cls_name = view.__class__.__name__
        raise TypeError(
            f"view must be a callable, pass {view_cls_name} or {view_cls_name}.as_view(*args, **kwargs), not "
            f"{view_cls_name}()."
        )

    # You typically pass a View class and we call as_view() for you
    if isinstance(view, type) and issubclass(view, View):
        return URLPattern(pattern=pattern, view=view.as_view(), name=name)

    # If you called View.as_view() yourself (or technically any callable)
    if callable(view):
        return URLPattern(pattern=pattern, view=view, name=name)

    raise TypeError("view must be a View class or View.as_view()")


routers_registry = RoutersRegistry()


def register_router(router_class):
    """Decorator to register a router class"""
    routers_registry.register_router(router_class)
    return router_class  # Return the class, not the instance
