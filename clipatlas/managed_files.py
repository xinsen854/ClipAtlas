"""Checks for app-owned directory operations; never follow filesystem links."""

import os
import shutil
from pathlib import Path


def validate_tree(root: Path, target: Path) -> None:
    root, target = root.absolute(), target.absolute()
    if (root == root.parent and target == root) or root.resolve() != root or target.resolve() != target:
        raise ValueError("Managed path must not be a drive root, symbolic link or junction")
    if not target.is_relative_to(root):
        raise ValueError("Path is outside the managed directory")
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError("Expected a managed directory")
    for directory, subdirs, files in os.walk(target, followlinks=False):
        for entry in [Path(directory), *(Path(directory)/name for name in subdirs+files)]:
            if entry.is_symlink() or entry.is_junction():
                raise ValueError("Managed directory contains a symbolic link or junction")


def remove_tree(root: Path, target: Path) -> None:
    validate_tree(root, target)
    if target.exists():
        shutil.rmtree(target)
