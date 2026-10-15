"""Private UUID-only storage and bounded format checks; no content is sent to models."""
from pathlib import Path
import re
import struct
import unicodedata
import time
import zlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from app.core.config import settings

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024


def storage_root():
    return Path(settings.IT_ATTACHMENT_ROOT or Path(__file__).resolve().parents[3] / ".local" / "attachments").resolve()


def uuid_name(value):
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError):
        return False


def storage_path(key, root=None):
    root = Path(root or storage_root()).resolve()
    parts = key.split("/")
    if len(parts) != 2 or not all(uuid_name(part) for part in parts):
        raise ValueError("Invalid private attachment key")
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Attachment path escapes storage root")
    return path


def safe_filename(name):
    if not name or len(name) > 180 or name.strip() != name or any(unicodedata.category(c).startswith("C") for c in name):
        raise HTTPException(422, "附件文件名无效")
    if any(c in name for c in '/\\:*?"<>|') or name in (".", ".."):
        raise HTTPException(422, "附件文件名不能包含路径或特殊字符")
    if Path(name).suffix.lower() not in (".png", ".jpg", ".jpeg", ".txt", ".log"):
        raise HTTPException(422, "仅支持 PNG、JPEG、UTF-8 TXT / LOG")
    return name


def validated_type(name, content):
    ext = Path(name).suffix.lower()
    valid = False
    if ext == ".png":
        # Check the complete chunk structure and CRC, rather than trusting MIME or magic alone.
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            offset, chunks = 8, []
            while offset + 12 <= len(content):
                length = struct.unpack(">I", content[offset:offset+4])[0]
                kind = content[offset+4:offset+8]
                end = offset + 12 + length
                if end > len(content) or zlib.crc32(content[offset+4:end-4]) & 0xffffffff != struct.unpack(">I", content[end-4:end])[0]:
                    break
                chunks.append(kind)
                if kind == b"IHDR" and (length != 13 or not all(struct.unpack(">II", content[offset+8:offset+16]))):
                    break
                offset = end
                if kind == b"IEND":
                    valid = chunks[0] == b"IHDR" and b"IDAT" in chunks and length == 0 and offset == len(content)
                    break
        mime = "image/png"
    elif ext in (".jpg", ".jpeg"):
        # JPEG marker/segment structure, including a frame and an entropy-coded scan.
        offset, frame, scan = 2, False, False
        if content.startswith(b"\xff\xd8") and content.endswith(b"\xff\xd9"):
            while offset + 1 < len(content):
                if content[offset] != 255:
                    break
                while offset < len(content) and content[offset] == 255:
                    offset += 1
                if offset >= len(content):
                    break
                marker = content[offset]; offset += 1
                if marker == 217:
                    valid = frame and scan and offset == len(content)
                    break
                if marker in range(208, 216) or marker == 1:
                    continue
                if offset + 2 > len(content):
                    break
                length = int.from_bytes(content[offset:offset+2], "big")
                if length < 2 or offset + length > len(content):
                    break
                if marker in (192, 193, 194):
                    frame = length >= 8 and all(struct.unpack(">HH", content[offset+3:offset+7]))
                offset += length
                if marker == 218:
                    scan = True
                    while offset + 1 < len(content):
                        if content[offset] == 255 and content[offset+1] not in (0, *range(208, 216)):
                            break
                        offset += 2 if content[offset] == 255 else 1
        mime = "image/jpeg"
    else:
        try:
            text = content.decode("utf-8-sig")
            valid = bool(text) and not any(ord(c) < 32 and c not in "\t\n\r" for c in text)
            if re.match(r"\s*(<!doctype\s+html|<html|<svg|<script)", text, re.I):
                valid = False
        except UnicodeDecodeError:
            valid = False
        mime = "text/plain; charset=utf-8"
    if not valid:
        raise HTTPException(422, "文件内容与支持的图片或 UTF-8 文本格式不符")
    return mime


async def cleanup_orphans(db, root=None, grace_seconds=86400, dry_run=True, now=None, limit=1000):
    """Only old UUID objects / .tmp-UUID files; protect every DB reference, including tombstones."""
    from app.helpdesk.models import HelpdeskTicketAttachment
    if grace_seconds < 3600 or not 1 <= limit <= 1000:
        raise ValueError("Cleanup requires at least one hour grace and a bounded limit")
    root = Path(root or storage_root()).resolve()
    references = set((await db.scalars(select(HelpdeskTicketAttachment.storage_key))).all())
    removed = []
    if not root.exists():
        return removed
    cutoff = (time.time() if now is None else now) - grace_seconds
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or not uuid_name(folder.name):
            continue
        for path in folder.iterdir():
            name = path.name.removeprefix(".tmp-")
            if path.is_symlink() or not path.is_file() or not uuid_name(name):
                continue
            resolved = path.resolve()
            key = f"{folder.name}/{path.name}"
            if not resolved.is_relative_to(root) or key in references or path.stat().st_mtime >= cutoff:
                continue
            removed.append(key)
            if not dry_run:
                resolved.unlink(missing_ok=True)
            if len(removed) >= limit:
                return removed
    return removed
