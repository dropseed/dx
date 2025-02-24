from collections import Counter

from plain.runtime import settings

from . import Error, Warning, register


@register
def check_url_config(package_configs, **kwargs):
    if getattr(settings, "URLS_MODULE", None):
        from plain.urls import get_resolver

        resolver = get_resolver()
        return check_resolver(resolver)
    return []


def check_resolver(resolver):
    """
    Recursively check the resolver.
    """
    check_method = getattr(resolver, "check", None)
    if check_method is not None:
        return check_method()
    elif not hasattr(resolver, "resolve"):
        return get_warning_for_invalid_pattern(resolver)
    else:
        return []


@register
def check_url_namespaces_unique(package_configs, **kwargs):
    """
    Warn if URL namespaces used in applications aren't unique.
    """
    if not getattr(settings, "URLS_MODULE", None):
        return []

    from plain.urls import get_resolver

    resolver = get_resolver()
    all_namespaces = _load_all_namespaces(resolver)
    counter = Counter(all_namespaces)
    non_unique_namespaces = [n for n, count in counter.items() if count > 1]
    errors = []
    for namespace in non_unique_namespaces:
        errors.append(
            Warning(
                f"URL namespace '{namespace}' isn't unique. You may not be able to reverse "
                "all URLs in this namespace",
                id="urls.W005",
            )
        )
    return errors


def _load_all_namespaces(resolver, parents=()):
    """
    Recursively load all namespaces from URL patterns.
    """
    url_patterns = getattr(resolver, "url_patterns", [])
    namespaces = [
        ":".join(parents + (url.namespace,))
        for url in url_patterns
        if getattr(url, "namespace", None) is not None
    ]
    for pattern in url_patterns:
        namespace = getattr(pattern, "namespace", None)
        current = parents
        if namespace is not None:
            current += (namespace,)
        namespaces.extend(_load_all_namespaces(pattern, current))
    return namespaces


def get_warning_for_invalid_pattern(pattern):
    """
    Return a list containing a warning that the pattern is invalid.

    describe_pattern() cannot be used here, because we cannot rely on the
    urlpattern having regex or name attributes.
    """
    if isinstance(pattern, str):
        hint = (
            f"Try removing the string '{pattern}'. The list of urlpatterns should not "
            "have a prefix string as the first element."
        )
    elif isinstance(pattern, tuple):
        hint = "Try using path() instead of a tuple."
    else:
        hint = None

    return [
        Error(
            f"Your URL pattern {pattern!r} is invalid. Ensure that urlpatterns is a list "
            "of path() and/or re_path() instances.",
            hint=hint,
            id="urls.E004",
        )
    ]
