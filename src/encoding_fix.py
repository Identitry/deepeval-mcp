"""Force UTF-8 encoding for all Python operations.

This module must be imported before any other modules to ensure
all I/O operations use UTF-8 encoding, preventing ascii codec errors.
"""

import io
import locale
import sys

# Reconfigure stdout and stderr to use UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Override sys.stdout/stderr with UTF-8 wrappers for older Python
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True
    )

if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True
    )

# Set default encoding for string operations
if hasattr(sys, 'setdefaultencoding'):
    sys.setdefaultencoding('utf-8')  # type: ignore

# Set locale
try:
    locale.setlocale(locale.LC_ALL, 'C.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        # Fall back to setting just LC_CTYPE
        try:
            locale.setlocale(locale.LC_CTYPE, 'C.UTF-8')
        except locale.Error:
            pass
