"""
This module converts requested URLs to callback view functions.

URLResolver is the main class here. Its resolve() method takes a URL (as
a string) and returns a ResolverMatch object which provides access to all
attributes of the resolved URL match.
"""

import functools
import re
from importlib import import_module
from pickle import PicklingError
from threading import local
from urllib.parse import quote

from plain.preflight.urls import check_resolver
from plain.runtime import settings
from plain.utils.datastructures import MultiValueDict
from plain.utils.http import RFC3986_SUBDELIMS, escape_leading_slashes
from plain.utils.regex_helper import normalize

from .exceptions import NoReverseMatch, Resolver404
from .patterns import RegexPattern, URLPattern


class ResolverMatch:
    def __init__(
        self,
        func,
        args,
        kwargs,
        url_name=None,
        namespaces=None,
        route=None,
        tried=None,
        captured_kwargs=None,
        extra_kwargs=None,
    ):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.url_name = url_name
        self.route = route
        self.tried = tried
        self.captured_kwargs = captured_kwargs
        self.extra_kwargs = extra_kwargs

        # If a URLRegexResolver doesn't have a namespace or namespace, it passes
        # in an empty value.
        self.namespaces = [x for x in namespaces if x] if namespaces else []
        self.namespace = ":".join(self.namespaces)

        if hasattr(func, "view_class"):
            func = func.view_class
        if not hasattr(func, "__name__"):
            # A class-based view
            self._func_path = func.__class__.__module__ + "." + func.__class__.__name__
        else:
            # A function-based view
            self._func_path = func.__module__ + "." + func.__name__

        view_path = url_name or self._func_path
        self.view_name = ":".join(self.namespaces + [view_path])

    def __repr__(self):
        if isinstance(self.func, functools.partial):
            func = repr(self.func)
        else:
            func = self._func_path
        return (
            "ResolverMatch(func={}, args={!r}, kwargs={!r}, url_name={!r}, "
            "namespaces={!r}, route={!r}{}{})".format(
                func,
                self.args,
                self.kwargs,
                self.url_name,
                self.namespaces,
                self.route,
                f", captured_kwargs={self.captured_kwargs!r}"
                if self.captured_kwargs
                else "",
                f", extra_kwargs={self.extra_kwargs!r}" if self.extra_kwargs else "",
            )
        )

    def __reduce_ex__(self, protocol):
        raise PicklingError(f"Cannot pickle {self.__class__.__qualname__}.")


def get_resolver(urls_module=None):
    if urls_module is None:
        urls_module = settings.URLS_MODULE

    return _get_cached_resolver(urls_module)


@functools.cache
def _get_cached_resolver(urls_module):
    from .routers import routers_registry

    if isinstance(urls_module, str):
        # Need to trigger an import in order for the @register_router
        # decorators to run. So this is a sensible entrypoint to do that,
        # usually just for the root URLS_MODULE but could be for anything.
        urls_module = import_module(urls_module)

    router = routers_registry.get_module_router(urls_module)
    return URLResolver(pattern=RegexPattern(r"^/"), router=router)


@functools.cache
def get_ns_resolver(ns_pattern, resolver, converters):
    from .routers import RouterBase

    # Build a namespaced resolver for the given parent urls_module pattern.
    # This makes it possible to have captured parameters in the parent
    # urls_module pattern.
    pattern = RegexPattern(ns_pattern)
    pattern.converters = dict(converters)

    class _NestedRouter(RouterBase):
        namespace = ""
        urls = resolver.url_patterns

    ns_resolver = URLResolver(pattern=pattern, router=_NestedRouter())

    class _NamespacedRouter(RouterBase):
        namespace = ""
        urls = [ns_resolver]

    return URLResolver(
        pattern=RegexPattern(r"^/"),
        router=_NamespacedRouter(),
    )


class URLResolver:
    def __init__(
        self,
        *,
        pattern,
        router,
    ):
        self.pattern = pattern
        self.router = router
        self._reverse_dict = {}
        self._namespace_dict = {}
        self._app_dict = {}
        self._populated = False
        self._local = local()

        # Set these immediately, in part so we can find routers
        # where the attributes weren't set correctly.
        self.namespace = self.router.namespace
        self.url_patterns = self.router.urls

    def __repr__(self):
        return f"<{self.__class__.__name__} {repr(self.router)} ({self.namespace}) {self.pattern.describe()}>"

    def check(self):
        messages = []
        for pattern in self.url_patterns:
            messages.extend(check_resolver(pattern))
        return messages or self.pattern.check()

    def _populate(self):
        # Short-circuit if called recursively in this thread to prevent
        # infinite recursion. Concurrent threads may call this at the same
        # time and will need to continue, so set 'populating' on a
        # thread-local variable.
        if getattr(self._local, "populating", False):
            return
        try:
            self._local.populating = True
            lookups = MultiValueDict()
            namespaces = {}
            packages = {}
            for url_pattern in reversed(self.url_patterns):
                p_pattern = url_pattern.pattern.regex.pattern
                p_pattern = p_pattern.removeprefix("^")
                if isinstance(url_pattern, URLPattern):
                    bits = normalize(url_pattern.pattern.regex.pattern)
                    lookups.appendlist(
                        url_pattern.view,
                        (
                            bits,
                            p_pattern,
                            url_pattern.pattern.converters,
                        ),
                    )
                    if url_pattern.name is not None:
                        lookups.appendlist(
                            url_pattern.name,
                            (
                                bits,
                                p_pattern,
                                url_pattern.pattern.converters,
                            ),
                        )
                else:  # url_pattern is a URLResolver.
                    url_pattern._populate()
                    if url_pattern.namespace:
                        packages.setdefault(url_pattern.namespace, []).append(
                            url_pattern.namespace
                        )
                        namespaces[url_pattern.namespace] = (p_pattern, url_pattern)
                    else:
                        for name in url_pattern.reverse_dict:
                            for (
                                _,
                                pat,
                                converters,
                            ) in url_pattern.reverse_dict.getlist(name):
                                new_matches = normalize(p_pattern + pat)
                                lookups.appendlist(
                                    name,
                                    (
                                        new_matches,
                                        p_pattern + pat,
                                        {
                                            **self.pattern.converters,
                                            **url_pattern.pattern.converters,
                                            **converters,
                                        },
                                    ),
                                )
                        for namespace, (
                            prefix,
                            sub_pattern,
                        ) in url_pattern.namespace_dict.items():
                            current_converters = url_pattern.pattern.converters
                            sub_pattern.pattern.converters.update(current_converters)
                            namespaces[namespace] = (p_pattern + prefix, sub_pattern)
                        for (
                            namespace,
                            namespace_list,
                        ) in url_pattern.app_dict.items():
                            packages.setdefault(namespace, []).extend(namespace_list)
            self._namespace_dict = namespaces
            self._app_dict = packages
            self._reverse_dict = lookups
            self._populated = True
        finally:
            self._local.populating = False

    @property
    def reverse_dict(self):
        if not self._reverse_dict:
            self._populate()
        return self._reverse_dict

    @property
    def namespace_dict(self):
        if not self._namespace_dict:
            self._populate()
        return self._namespace_dict

    @property
    def app_dict(self):
        if not self._app_dict:
            self._populate()
        return self._app_dict

    @staticmethod
    def _extend_tried(tried, pattern, sub_tried=None):
        if sub_tried is None:
            tried.append([pattern])
        else:
            tried.extend([pattern, *t] for t in sub_tried)

    @staticmethod
    def _join_route(route1, route2):
        """Join two routes, without the starting ^ in the second route."""
        if not route1:
            return route2
        route2 = route2.removeprefix("^")
        return route1 + route2

    def resolve(self, path):
        path = str(path)  # path may be a reverse_lazy object
        tried = []
        match = self.pattern.match(path)
        if match:
            new_path, args, kwargs = match
            for pattern in self.url_patterns:
                try:
                    sub_match = pattern.resolve(new_path)
                except Resolver404 as e:
                    self._extend_tried(tried, pattern, e.args[0].get("tried"))
                else:
                    if sub_match:
                        # Merge captured arguments in match with submatch
                        # Update the sub_match_dict with the kwargs from the sub_match.
                        sub_match_dict = {**kwargs, **sub_match.kwargs}
                        # If there are *any* named groups, ignore all non-named groups.
                        # Otherwise, pass all non-named arguments as positional
                        # arguments.
                        sub_match_args = sub_match.args
                        if not sub_match_dict:
                            sub_match_args = args + sub_match.args
                        current_route = (
                            ""
                            if isinstance(pattern, URLPattern)
                            else str(pattern.pattern)
                        )
                        self._extend_tried(tried, pattern, sub_match.tried)
                        return ResolverMatch(
                            sub_match.func,
                            sub_match_args,
                            sub_match_dict,
                            sub_match.url_name,
                            [self.namespace] + sub_match.namespaces,
                            self._join_route(current_route, sub_match.route),
                            tried,
                            captured_kwargs=sub_match.captured_kwargs,
                            extra_kwargs=sub_match.extra_kwargs,
                        )
                    tried.append([pattern])
            raise Resolver404({"tried": tried, "path": new_path})
        raise Resolver404({"path": path})

    def reverse(self, lookup_view, *args, **kwargs):
        if args and kwargs:
            raise ValueError("Don't mix *args and **kwargs in call to reverse()!")

        if not self._populated:
            self._populate()

        possibilities = self.reverse_dict.getlist(lookup_view)

        for possibility, pattern, converters in possibilities:
            for result, params in possibility:
                if args:
                    if len(args) != len(params):
                        continue
                    candidate_subs = dict(zip(params, args))
                else:
                    if set(kwargs).symmetric_difference(params):
                        continue
                    candidate_subs = kwargs
                # Convert the candidate subs to text using Converter.to_url().
                text_candidate_subs = {}
                match = True
                for k, v in candidate_subs.items():
                    if k in converters:
                        try:
                            text_candidate_subs[k] = converters[k].to_url(v)
                        except ValueError:
                            match = False
                            break
                    else:
                        text_candidate_subs[k] = str(v)
                if not match:
                    continue
                # WSGI provides decoded URLs, without %xx escapes, and the URL
                # resolver operates on such URLs. First substitute arguments
                # without quoting to build a decoded URL and look for a match.
                # Then, if we have a match, redo the substitution with quoted
                # arguments in order to return a properly encoded URL.

                # There was a lot of script_prefix handling code before,
                # so this is a crutch to leave the below as-is for now.
                _prefix = "/"

                candidate_pat = _prefix.replace("%", "%%") + result
                if re.search(
                    f"^{re.escape(_prefix)}{pattern}",
                    candidate_pat % text_candidate_subs,
                ):
                    # safe characters from `pchar` definition of RFC 3986
                    url = quote(
                        candidate_pat % text_candidate_subs,
                        safe=RFC3986_SUBDELIMS + "/~:@",
                    )
                    # Don't allow construction of scheme relative urls.
                    return escape_leading_slashes(url)
        # lookup_view can be URL name or callable, but callables are not
        # friendly in error messages.
        m = getattr(lookup_view, "__module__", None)
        n = getattr(lookup_view, "__name__", None)
        if m is not None and n is not None:
            lookup_view_s = f"{m}.{n}"
        else:
            lookup_view_s = lookup_view

        patterns = [pos[1] for pos in possibilities]
        if patterns:
            if args:
                arg_msg = f"arguments '{args}'"
            elif kwargs:
                arg_msg = f"keyword arguments '{kwargs}'"
            else:
                arg_msg = "no arguments"
            msg = "Reverse for '%s' with %s not found. %d pattern(s) tried: %s" % (  # noqa: UP031
                lookup_view_s,
                arg_msg,
                len(patterns),
                patterns,
            )
        else:
            msg = (
                f"Reverse for '{lookup_view_s}' not found. '{lookup_view_s}' is not "
                "a valid view function or pattern name."
            )
        raise NoReverseMatch(msg)
