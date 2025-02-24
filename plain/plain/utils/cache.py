"""
This module contains helper functions for controlling caching. It does so by
managing the "Vary" header of responses. It includes functions to patch the
header of response objects directly and decorators that change functions to do
that header-patching themselves.

For information on the Vary header, see RFC 9110 Section 12.5.5.

Essentially, the "Vary" HTTP header defines which headers a cache should take
into account when building its cache key. Requests with the same path but
different header content for headers named in "Vary" need to get different
cache keys to prevent delivery of wrong content.

An example: i18n middleware would need to distinguish caches by the
"Accept-language" header.
"""

from collections import defaultdict

from plain.utils.regex_helper import _lazy_re_compile

cc_delim_re = _lazy_re_compile(r"\s*,\s*")


def patch_cache_control(response, **kwargs):
    """
    Patch the Cache-Control header by adding all keyword arguments to it.
    The transformation is as follows:

    * All keyword parameter names are turned to lowercase, and underscores
      are converted to hyphens.
    * If the value of a parameter is True (exactly True, not just a
      true value), only the parameter name is added to the header.
    * All other parameters are added with their value, after applying
      str() to it.
    """

    def dictitem(s):
        t = s.split("=", 1)
        if len(t) > 1:
            return (t[0].lower(), t[1])
        else:
            return (t[0].lower(), True)

    def dictvalue(*t):
        if t[1] is True:
            return t[0]
        else:
            return f"{t[0]}={t[1]}"

    cc = defaultdict(set)
    if response.headers.get("Cache-Control"):
        for field in cc_delim_re.split(response.headers["Cache-Control"]):
            directive, value = dictitem(field)
            if directive == "no-cache":
                # no-cache supports multiple field names.
                cc[directive].add(value)
            else:
                cc[directive] = value

    # If there's already a max-age header but we're being asked to set a new
    # max-age, use the minimum of the two ages. In practice this happens when
    # a decorator and a piece of middleware both operate on a given view.
    if "max-age" in cc and "max_age" in kwargs:
        kwargs["max_age"] = min(int(cc["max-age"]), kwargs["max_age"])

    # Allow overriding private caching and vice versa
    if "private" in cc and "public" in kwargs:
        del cc["private"]
    elif "public" in cc and "private" in kwargs:
        del cc["public"]

    for k, v in kwargs.items():
        directive = k.replace("_", "-")
        if directive == "no-cache":
            # no-cache supports multiple field names.
            cc[directive].add(v)
        else:
            cc[directive] = v

    directives = []
    for directive, values in cc.items():
        if isinstance(values, set):
            if True in values:
                # True takes precedence.
                values = {True}
            directives.extend([dictvalue(directive, value) for value in values])
        else:
            directives.append(dictvalue(directive, values))
    cc = ", ".join(directives)
    response.headers["Cache-Control"] = cc


def patch_vary_headers(response, newheaders):
    """
    Add (or update) the "Vary" header in the given Response object.
    newheaders is a list of header names that should be in "Vary". If headers
    contains an asterisk, then "Vary" header will consist of a single asterisk
    '*'. Otherwise, existing headers in "Vary" aren't removed.
    """
    # Note that we need to keep the original order intact, because cache
    # implementations may rely on the order of the Vary contents in, say,
    # computing an MD5 hash.
    if "Vary" in response.headers:
        vary_headers = cc_delim_re.split(response.headers["Vary"])
    else:
        vary_headers = []
    # Use .lower() here so we treat headers as case-insensitive.
    existing_headers = {header.lower() for header in vary_headers}
    additional_headers = [
        newheader
        for newheader in newheaders
        if newheader.lower() not in existing_headers
    ]
    vary_headers += additional_headers
    if "*" in vary_headers:
        response.headers["Vary"] = "*"
    else:
        response.headers["Vary"] = ", ".join(vary_headers)


def _to_tuple(s):
    t = s.split("=", 1)
    if len(t) == 2:
        return t[0].lower(), t[1]
    return t[0].lower(), True
