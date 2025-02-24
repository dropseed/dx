import functools
import inspect


@functools.lru_cache(maxsize=512)
def _get_func_parameters(func, remove_first):
    parameters = tuple(inspect.signature(func).parameters.values())
    if remove_first:
        parameters = parameters[1:]
    return parameters


def _get_callable_parameters(meth_or_func):
    is_method = inspect.ismethod(meth_or_func)
    func = meth_or_func.__func__ if is_method else meth_or_func
    return _get_func_parameters(func, remove_first=is_method)


def get_func_args(func):
    params = _get_callable_parameters(func)
    return [
        param.name
        for param in params
        if param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]


def func_accepts_kwargs(func):
    """Return True if function 'func' accepts keyword arguments **kwargs."""
    return any(p for p in _get_callable_parameters(func) if p.kind == p.VAR_KEYWORD)


def method_has_no_args(meth):
    """Return True if a method only accepts 'self'."""
    count = len(
        [p for p in _get_callable_parameters(meth) if p.kind == p.POSITIONAL_OR_KEYWORD]
    )
    return count == 0 if inspect.ismethod(meth) else count == 1
