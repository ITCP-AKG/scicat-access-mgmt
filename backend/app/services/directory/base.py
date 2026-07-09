"""Directory provider protocol (T010).

A pluggable source of users. v1 implementation reads SciCat identities; a future
LDAP/AD provider implements the same protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ...models.directory import DirectoryUser


@runtime_checkable
class DirectoryProvider(Protocol):
    async def search(self, query: str, limit: int = 25) -> list[DirectoryUser]: ...

    async def get(self, user_id: str) -> DirectoryUser | None: ...

    async def list(self, limit: int = 1000) -> list[DirectoryUser]: ...

    async def is_active(self, user_id: str) -> bool: ...
