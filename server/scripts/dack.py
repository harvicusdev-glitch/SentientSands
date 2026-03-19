# MIT License
#
# Copyright (c) 2026 Marisha Lozada-Norcross
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import platform
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, Union


EXTDEFAULT = '.cfg'


# =========================
# Helper Functions
# =========================

def _ensure_dir(dirpath, mkdir=True, mode: int = 0o700) -> bool:
    path = Path(dirpath).expanduser().resolve()

    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(
                f"Config path exists but is not a directory: {path}"
            )
        return True

    elif mkdir:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f"Cannot create config directory {path}: {e}"
            )

        if platform.system() != 'Windows':
            try:
                path.chmod(mode)
            except OSError:
                pass
        return True

    else:
        return False


def _ensure_file(file: Union[str, Path]) -> Path:
    if not file:
        raise ValueError(
            f"Invalid file (file name or path cannot be empty or None)"
        )

    filepath = Path(file)
    filename = filepath.name
    filestem, period, fileext = filename.rpartition('.')
    if not period:
        filestem = fileext
        fileext = EXTDEFAULT
    if not filestem:
        raise ValueError(
            f"Invalid filestem (filestem cannot be empty or None)"
        )
    if not fileext:
        fileext = EXTDEFAULT
    else:
        fileext = _ensure_ext(period + fileext)
    filename = filestem + fileext

    return filepath.parent / filename


def _ensure_ext(extension: str) -> str:
    if not extension or not extension.strip():
        extension = EXTDEFAULT
    extension = extension.strip().lower()
    if extension[0] != '.':
        extension = '.' + extension
    return extension


def _ensure_filename(filename: str) -> str:
    if not filename:
        raise ValueError(
            f"Invalid filename (filename cannot be empty or None)"
        )

    safename = Path(filename).name
    if not safename or safename != filename:
        raise ValueError(
            f"Invalid filename (path traversal detected): {filename}"
        )

    return safename


def _find_files(dirpath: Union[str, Path], exts: Union[str, list[str]] = EXTDEFAULT) -> list[Path]:
    dirpath = Path(dirpath)
    if not _ensure_dir(dirpath, mkdir=False):
        return []
    if isinstance(exts, list):
        exts = [_ensure_ext(ext) for ext in exts]
        exts = list(set(exts))
    else:
        exts = [_ensure_ext(str(exts))]

    filepaths: list[Path] = []
    for ext in exts:
        filepaths.extend(dirpath.rglob(f'*{ext}'))
    return filepaths


# =========================
# Saving Functions
# =========================

def from_pydict(data: Dict[str, Any]) -> str:
    return '&>' + '\n&>'.join(f"{k.strip()}:{str(v).strip()}" for k, v in data.items())


def saveas(data: Dict[str, str], dirpath: Union[str, Path], filestem: str, fileext: str = EXTDEFAULT, atomic=True, mode: int = 0o600):
    dirpath = Path(dirpath)
    fileext = _ensure_ext(fileext)
    filename = _ensure_filename(filestem + fileext)
    filepath = dirpath / filename
    save(data, filepath, atomic, mode)


def savefile(data: Dict[str, str], dirpath: Union[str, Path], filename: str, atomic=True, mode: int = 0o600):
    dirpath = Path(dirpath)
    filename = _ensure_filename(filename)
    filepath = dirpath / filename
    save(data, filepath, atomic, mode)


def savebatch(dataset: Dict[str, Dict[str, str]], dirpath: Union[str, Path], subdirpath: Dict[str, Union[str, Path]] = {}, fileexts: Dict[str, str] = {}, atomic=True, mode: int = 0o600):
    dirpath = Path(dirpath)
    for datakey in dataset:
        curr_subdirpath = Path("")
        if subdirpath:
            curr_subdirpath = Path(subdirpath[datakey])

        safekey = _ensure_filename(datakey)
        safeext = _ensure_ext(fileexts[datakey])
        filepath = dirpath / curr_subdirpath / (safekey + safeext)
        data = dataset[datakey]
        save(data, filepath, atomic, mode)


def save(data: Dict[str, str], filepath: Union[str, Path], atomic=True, mode: int = 0o600):
    filepath = _ensure_file(filepath)
    _ensure_dir(filepath.parent)

    dack = from_pydict(data)
    encoded = dack.encode('utf-8')

    if atomic:
        fd = None
        tmppath = None
        try:
            fd, tmppath = tempfile.mkstemp(
                dir=filepath.parent,
                prefix=f".{filepath.name}.tmp."
            )

            with os.fdopen(fd, 'wb') as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
                fd = None
            fd = None
            os.replace(tmppath, filepath)
            tmppath = None
        except:
            if fd:
                os.close(fd)
            if tmppath and os.path.exists(tmppath):
                os.unlink(tmppath)
            raise
    else:
        filepath.write_bytes(encoded)

    if platform.system() != 'Windows':
        try:
            filepath.chmod(mode)
        except OSError:
            pass


# =========================
# Loading Functions
# =========================

def to_pydict(text: str) -> Dict[str, str]:
    entries = text.split('&>')[1:]
    dackdict: Dict[str, str] = {}
    for entry in entries:
        if not entry.strip():
            continue
        key, sep, value = entry.partition(':')
        key = key.strip()
        value = value.strip()
        if key and sep:
            if key in dackdict:
                warnings.warn(f"Duplicate key '{key}', keeping first value")
                continue
            dackdict[key] = value
    return dackdict


def loadfrom(dirpath: Union[str, Path], filestem: str, fileext: str = EXTDEFAULT) -> Dict[str, str]:
    dirpath = Path(dirpath)
    filepath = dirpath / (filestem + fileext)
    return load(filepath)


def loadfile(dirpath: Union[str, Path], filename: str) -> Dict[str, str]:
    dirpath = Path(dirpath)
    filepath = dirpath / filename
    return load(filepath)


def loadbatch(dirpath: Union[str, Path], exts: Union[str, list[str]] = EXTDEFAULT) -> tuple[Dict[str, Dict[str, str]], Dict[str, Union[str, Path]], Dict[str, str]]:
    dirpath = Path(dirpath)
    _ensure_dir(dirpath)

    filepaths = _find_files(dirpath, exts)
    if not filepaths:
        return {}, {}, {}

    batchfiles = {}
    batchsubdir = {}
    batchexts = {}
    for filepath in filepaths:
        batchfiles[filepath.stem] = load(filepath)
        batchsubdir[filepath.stem] = filepath.parent.relative_to(dirpath)
        batchexts[filepath.stem] = filepath.suffix

    return batchfiles, batchsubdir, batchexts


def load(filepath: Union[str, Path]) -> Dict[str, str]:
    filepath = Path(filepath)
    if not _ensure_dir(filepath.parent, mkdir=False):
        return {}

    if filepath.is_symlink():
        filepath = filepath.resolve()

    if not filepath.is_file():
        return {}

    text = filepath.read_text(encoding='utf-8-sig', errors='replace')
    if not text:
        return {}
    return to_pydict(text)


# =========================
# Public API
# =========================

__all__ = [
    'from_pydict', 'save', 'saveas', 'savefile', 'savebatch',
    'to_pydict', 'load', 'loadfrom', 'loadfile', 'loadbatch'
]
