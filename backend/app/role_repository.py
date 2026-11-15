"""Parameterized, read-only lookup of server-owned role assignments."""
from dataclasses import dataclass
from uuid import UUID

from backend.app.config import ReadOnlyDatabaseSettings
from backend.app.database import DatabaseReadError, read_connection

ROLE_SQL = 'SELECT user_id, role, enabled FROM app_security.user_roles WHERE user_id = %s'


class RoleSourceUnavailable(Exception):
    """No authorization fallback is allowed when the trusted source fails."""


@dataclass(frozen=True)
class RoleAssignment:
    user_id: UUID
    role: str
    enabled: bool


class RoleRepository:
    def __init__(self, settings: ReadOnlyDatabaseSettings) -> None:
        self.settings = settings

    def find(self, user_id: UUID) -> RoleAssignment | None:
        try:
            with read_connection(self.settings) as connection:
                with connection.cursor() as cursor:
                    # Identity is verified in FastAPI, not supplied by a session setting.
                    cursor.execute(ROLE_SQL, (user_id,))
                    row = cursor.fetchone()
            if row is None:
                return None
            return RoleAssignment(user_id=UUID(str(row[0])), role=row[1], enabled=row[2])
        except (DatabaseReadError, ValueError, TypeError, IndexError):
            raise RoleSourceUnavailable() from None
