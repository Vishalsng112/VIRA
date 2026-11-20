"""Pluggable object storage for attachments, exports and large artifacts."""
from .service import get_backend, put, get_record, read, delete, list_objects

__all__ = ["get_backend", "put", "get_record", "read", "delete", "list_objects"]
