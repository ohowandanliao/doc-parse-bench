"""Reuse successful upstream LaTeX conversions without caching failure fallbacks."""

from functools import lru_cache, wraps


def install(module, maxsize=8192):
    original = module._latex_to_text_with_timeout

    class UncachedFailure(Exception):
        pass

    @lru_cache(maxsize=maxsize)
    def cached(latex, timeout):
        value = original(latex, timeout=timeout)
        if value is None:
            # Retain each call's original timeout/error handling and page context.
            raise UncachedFailure
        return value

    @wraps(original)
    def convert(latex, timeout=None):
        try:
            return cached(latex, module._resolve_timeout(timeout))
        except UncachedFailure:
            return None

    module._latex_to_text_with_timeout = convert
    return cached
