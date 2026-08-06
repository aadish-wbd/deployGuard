"""Payload size limits enforced by the API (REQUIREMENTS.md "Payload Size Limits").

Single source of truth shared by app.config defaults and app.models.schemas
field constraints so the two can't drift apart.
"""

MAX_ERROR_MESSAGE_CHARS = 500
MAX_STACK_TRACE_CHARS = 2000
MAX_LOG_SNIPPET_CHARS = 1500
MAX_NOTEBOOK_CONTEXT_CHARS = 8000
MAX_REQUEST_BODY_BYTES = 8 * 1024
