"""Local media storage. Each imported file gets its own folder: <storage_dir>/<media_id>/.

Production will swap this for Cloudflare R2, so keep all file access going through here.
"""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from app.media.probe import MediaInfo

CHUNK = 1024 * 1024
_MEDIA_ID = re.compile(r"^[0-9a-f]{32}$")


class UploadTooLarge(ValueError):
    pass


class MediaNotFound(KeyError):
    pass


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, media_id: str) -> Path:
        # media_id is always our own uuid hex; refuse anything else so paths can't escape root.
        if not _MEDIA_ID.match(media_id):
            raise MediaNotFound(media_id)
        return self.root / media_id

    def save_upload(self, stream: BinaryIO, extension: str, max_bytes: int) -> tuple[str, Path]:
        media_id = uuid.uuid4().hex
        folder = self._dir(media_id)
        folder.mkdir(parents=True)
        dest = folder / f"source{extension.lower()}"
        written = 0
        try:
            with dest.open("wb") as out:
                while chunk := stream.read(CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise UploadTooLarge(f"Upload is larger than the {max_bytes // (1024 * 1024)} MB limit")
                    out.write(chunk)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return media_id, dest

    def folder(self, media_id: str) -> Path:
        folder = self._dir(media_id)
        if not folder.is_dir():
            raise MediaNotFound(media_id)
        return folder

    def source_path(self, media_id: str) -> Path:
        matches = sorted(self.folder(media_id).glob("source.*"))
        if not matches:
            raise MediaNotFound(media_id)
        return matches[0]

    def save_json(self, media_id: str, name: str, data: dict) -> None:
        (self.folder(media_id) / name).write_text(json.dumps(data, indent=2))

    def load_json(self, media_id: str, name: str) -> dict | None:
        path = self.folder(media_id) / name
        return json.loads(path.read_text()) if path.is_file() else None

    def save_info(self, media_id: str, info: MediaInfo, original_name: str) -> None:
        payload = {"media_id": media_id, "original_name": original_name, "info": info.model_dump()}
        (self._dir(media_id) / "info.json").write_text(json.dumps(payload, indent=2))

    def load_info(self, media_id: str) -> dict:
        path = self._dir(media_id) / "info.json"
        if not path.is_file():
            raise MediaNotFound(media_id)
        return json.loads(path.read_text())

    def delete(self, media_id: str) -> None:
        folder = self._dir(media_id)
        if not folder.exists():
            raise MediaNotFound(media_id)
        shutil.rmtree(folder)
