"""Shared read-only discovery for pending images and bounded batch history."""
import csv
import json
import os
from pathlib import Path

IMAGES = {'.jpg', '.jpeg', '.png'}


def pending_files(settings, mode='self_pickup'):
    root = Path(settings['pending_root'])
    factory = Path(settings.get('factory_pending_root', root / '厂发')).resolve()
    selected = Path(settings.get('self_pickup_pending_root', root / '自提')) if mode == 'self_pickup' else factory
    files = set()
    # Preserve legacy loose images; never mix factory notes into self-pickup.
    if mode == 'self_pickup' and root.is_dir() and root.resolve() != factory:
        files.update(p for p in root.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGES)
    if selected.is_dir():
        for directory, dirs, names in os.walk(selected, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()
                       and not (Path(directory)/d).is_junction()
                       and (mode == 'factory' or (Path(directory)/d).resolve() != factory)]
            for name in names:
                p = Path(directory)/name
                if p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGES:
                    files.add(p)
    return sorted(files)


def history_files(root):
    root = Path(root)
    locations = {root, root/'outputs'}
    for base in tuple(locations):
        if base.is_dir():
            locations.update(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()
                             and not p.is_junction() and p.name.startswith(('batch-', 'delivery-batch-')))
    paths = set()
    for base in locations:
        for pattern in ('*-result.csv', '*-manifest.csv', '*-result.json'):
            paths.update(base.glob(pattern))
    return sorted(p for p in paths if p.is_file() and not p.is_symlink())


def history_rows(root):
    for path in history_files(root):
        try:
            if path.suffix == '.csv':
                with path.open(encoding='utf-8-sig', newline='') as f:
                    rows = list(csv.DictReader(f))
            else:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
                rows = data.get('results', []) if isinstance(data, dict) else data
                rows = [dict(r, source_sha256=r.get('source_sha256', r.get('sha256', '')))
                        for r in rows if isinstance(r, dict)]
            for row in rows:
                yield path, row
        except (UnicodeError, csv.Error, json.JSONDecodeError):
            continue
