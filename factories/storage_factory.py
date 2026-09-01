from core.interfaces import StorageHandler
from infrastructure.storage.sqlite_handler import SQLiteStorageHandler

_storage_instance: StorageHandler | None = None

def get_storage_handler() -> StorageHandler:
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = SQLiteStorageHandler()
    return _storage_instance
