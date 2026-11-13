"""Canonical content, bounded artifact paths, and atomic small metadata writes."""

import hashlib
import json
import os
import uuid
from pathlib import Path, PurePosixPath


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':')).encode('utf-8')


def read_json(path: Path):
    def reject(value):
        raise ValueError(f'Non-finite JSON value: {value}')
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=reject)


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative:
        raise ValueError('Invalid relative artifact path.')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or '..' in pure.parts or pure.as_posix() != relative:
        raise ValueError('Invalid relative artifact path.')
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or result == root.resolve():
        raise ValueError('Artifact path leaves its output root.')
    return result


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_bytes(canonical(value) + b'\n')
    os.replace(temporary, path)
