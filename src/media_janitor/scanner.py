from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from .models import DirectoryContext, FileEntry, MediaKind, ScanSnapshot, relative_posix

AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".m4b",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}

VIDEO_EXTENSIONS = {
    ".avi",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".webm",
    ".wmv",
}


def classify_extension(extension: str) -> MediaKind:
    normalized = extension.lower()
    if normalized in AUDIO_EXTENSIONS:
        return MediaKind.AUDIOBOOK
    if normalized in VIDEO_EXTENSIONS:
        return MediaKind.VIDEO
    return MediaKind.OTHER


def scan_library(root: str | Path, *, include_other: bool = False) -> ScanSnapshot:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Library root does not exist: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"Library root is not a directory: {root_path}")

    entries: list[FileEntry] = []
    unreadable: list[str] = []
    files_by_directory: dict[Path, list[str]] = defaultdict(list)
    children_by_directory: dict[Path, list[str]] = defaultdict(list)
    seen_directories: set[Path] = {root_path}

    def onerror(error: OSError) -> None:
        filename = getattr(error, "filename", None)
        if filename:
            try:
                unreadable.append(relative_posix(Path(filename), root_path))
            except ValueError:
                unreadable.append(str(filename))
        else:
            unreadable.append(str(error))

    for current, directory_names, file_names in os.walk(root_path, topdown=True, onerror=onerror, followlinks=False):
        current_path = Path(current)
        seen_directories.add(current_path)
        directory_names.sort(key=str.casefold)
        file_names.sort(key=str.casefold)
        children_by_directory[current_path].extend(directory_names)

        for filename in file_names:
            file_path = current_path / filename
            extension = file_path.suffix.lower()
            media_kind = classify_extension(extension)
            if not include_other and media_kind is MediaKind.OTHER:
                continue

            try:
                size_bytes = file_path.stat().st_size
            except OSError:
                unreadable.append(relative_posix(file_path, root_path))
                continue

            files_by_directory[current_path].append(filename)
            entries.append(
                FileEntry(
                    relative_path=relative_posix(file_path, root_path),
                    size_bytes=size_bytes,
                    extension=extension,
                    media_kind=media_kind,
                )
            )

    sibling_map: dict[Path, tuple[str, ...]] = {}
    by_parent: dict[Path, list[Path]] = defaultdict(list)
    for directory in seen_directories:
        by_parent[directory.parent].append(directory)

    for directory in seen_directories:
        if directory == root_path:
            sibling_map[directory] = ()
            continue
        siblings = [child.name for child in by_parent[directory.parent] if child != directory]
        sibling_map[directory] = tuple(sorted(siblings, key=str.casefold))

    contexts: list[DirectoryContext] = []
    for directory in sorted(seen_directories, key=lambda path: relative_posix(path, root_path).casefold()):
        relative = relative_posix(directory, root_path)
        if directory == root_path:
            parent: str | None = None
        else:
            parent_value = relative_posix(directory.parent, root_path)
            parent = parent_value or "."

        contexts.append(
            DirectoryContext(
                relative_path=relative or ".",
                parent=parent,
                sibling_names=sibling_map[directory],
                file_names=tuple(files_by_directory[directory]),
                child_directory_names=tuple(children_by_directory[directory]),
            )
        )

    entries.sort(key=lambda entry: entry.relative_path.casefold())
    unreadable_unique = tuple(sorted(set(unreadable), key=str.casefold))
    return ScanSnapshot(
        root=str(root_path),
        files=tuple(entries),
        directories=tuple(contexts),
        unreadable_paths=unreadable_unique,
    )
