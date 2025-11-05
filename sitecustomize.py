"""
Site-wide customization for Python runtime.

This file is automatically imported by Python at startup and applies
to all code including third-party libraries.
"""

import io
import sys

# Force UTF-8 for stdout/stderr globally
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True
    )

if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True
    )

# Monkey-patch open() to default to UTF-8
import builtins
_original_open = builtins.open

def utf8_open(file, mode='r', *args, **kwargs):
    """Default to UTF-8 encoding for all file operations."""
    if 'b' not in mode and 'encoding' not in kwargs:
        kwargs['encoding'] = 'utf-8'
        kwargs.setdefault('errors', 'replace')
    return _original_open(file, mode, *args, **kwargs)

builtins.open = utf8_open

# Monkey-patch httpx header normalization to handle unicode
# This fixes the OpenAI SDK bug where unicode characters in headers cause ASCII encoding errors
try:
    import httpx._models

    _original_normalize = httpx._models._normalize_header_value

    def _normalize_header_value_utf8(value, encoding=None):
        """Normalize header value with UTF-8 support instead of ASCII-only."""
        if isinstance(value, bytes):
            return value
        elif isinstance(value, str):
            # Force UTF-8 encoding with error replacement instead of ASCII
            return value.encode('utf-8', errors='replace')
        else:
            # Handle other types (int, etc)
            return str(value).encode('utf-8', errors='replace')

    httpx._models._normalize_header_value = _normalize_header_value_utf8
except ImportError:
    # httpx not installed yet, will be patched when it loads
    pass
