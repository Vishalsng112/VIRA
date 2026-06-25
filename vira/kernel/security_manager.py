"""Permission enforcement and security"""
from loguru import logger
from typing import List, Set, Optional
from dataclasses import dataclass, field

# logger = logging.getLogger(__name__)


@dataclass
class Permission:
    resource: str
    action: str
    allowed: bool = True


class SecurityManager:
    """Enforces permissions on actions and event access"""

    def __init__(self):
        self._permissions: Set[str] = set()
        self._deny_rules: Set[str] = set()

    async def initialize(self, default_permissions: List[str] = None):
        """Initialize with default permissions"""
        if default_permissions:
            for perm in default_permissions:
                self._permissions.add(perm)
        logger.info(f"SecurityManager initialized with {len(self._permissions)} permissions")

    def authorize(self, action: str, resource: str = "*") -> bool:
        """Check if an action is authorized"""
        # Exact match
        full_action = f"{action}"
        if full_action in self._deny_rules:
            return False
        if full_action in self._permissions:
            return True

        # Wildcard check
        for perm in self._permissions:
            if perm.endswith(".*"):
                prefix = perm[:-2]
                if action.startswith(prefix):
                    return True

        return False

    def grant(self, permission: str) -> None:
        """Grant a permission"""
        self._permissions.add(permission)
        self._deny_rules.discard(permission)

    def revoke(self, permission: str) -> None:
        """Revoke a permission"""
        self._deny_rules.add(permission)
        self._permissions.discard(permission)

    def can_publish_event(self, event_type: str, source: str = "unknown") -> bool:
        """Check if event publishing is allowed"""
        return self.authorize(f"event.publish.{event_type}")

    def can_subscribe_event(self, event_type: str) -> bool:
        """Check if subscription is allowed"""
        return self.authorize(f"event.subscribe.{event_type}")

    def list_permissions(self) -> List[str]:
        """List all granted permissions"""
        return list(self._permissions)