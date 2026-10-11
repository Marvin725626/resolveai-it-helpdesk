"""Missing upstream storage adapter, repaired for local development."""
import asyncio
from pathlib import Path
from uuid import UUID


class LocalStorage:
    def __init__(self, root: Path | None = None):
        self.root = (root or Path("storage")).resolve()

    async def save_file(self, tenant_id: str, key: str, contents: bytes) -> str:
        tenant = str(UUID(tenant_id))
        if not key or Path(key).name != key or "/" in key or "\\" in key or ":" in key:
            raise ValueError("Unsafe storage key")
        path = (self.root / tenant / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage path outside root")
        def write():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        await asyncio.to_thread(write)
        return path.relative_to(self.root).as_posix()

    async def delete_file(self, key: str) -> None:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Storage path outside root")
        await asyncio.to_thread(path.unlink, missing_ok=True)


def get_storage_service() -> LocalStorage:
    return LocalStorage()
