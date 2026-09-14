"""Assemble a reviewable public tree without local data or nested Git history."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('destination', type=Path)
args = parser.parse_args()
destination = args.destination.resolve()
if destination.exists():
    parser.error('Destination already exists; use a fresh directory')
allowed_files = {'README.md', 'LICENSE', 'DATA_SOURCES.md', '.gitignore', '.dockerignore',
                 '.env.example', 'compose.yml'}
allowed_dirs = {'backend', 'frontend', 'scripts', 'deploy', 'database', 'docs'}
allowed_resources = {'resource/nipt_item_catalog.json', 'resource/item_marker.tsv',
                     'resource/glcp_standard_example.tsv'}
excluded_names = {'.git', '.openai', 'node_modules', 'dist', '.next', '.vinext', '.venv',
                  '__pycache__', '.pytest_cache', '.ruff_cache', '.wrangler', '.DS_Store'}
allowed_suffixes = {'.py', '.toml', '.ini', '.mako', '.ts', '.tsx', '.json', '.css', '.md',
                    '.mjs', '.txt', '.svg', '.woff2', '.conf', '.yml'}

def include(path):
    rel = path.relative_to(root)
    if any(part in excluded_names or part.endswith('.egg-info') for part in rel.parts):
        return False
    if path.is_symlink() or (path.name.startswith('.env') and path.name != '.env.example'):
        return False
    if path.name == 'actual_data_validation_2026-09-03.md':
        return False
    if rel.as_posix() in allowed_files | allowed_resources:
        return True
    if rel.parts[0] not in allowed_dirs:
        return False
    return path.suffix in allowed_suffixes or path.name in {'Dockerfile', '.gitignore', '.dockerignore', '.env.example'}

# Select before creating a destination beneath the working tree.
paths = [root / name for name in allowed_files]
for name in allowed_dirs:
    # Prune ignored trees without reading source data or build artifacts.
    import os
    for base, dirs, files in os.walk(root / name):
        dirs[:] = [d for d in dirs if d not in excluded_names and not d.endswith('.egg-info') and not (Path(base)/d).is_symlink()]
        paths.extend(Path(base)/f for f in files)
paths.extend(root / name for name in allowed_resources)
selected = sorted({p for p in paths if p.is_file() and include(p)})
manifest = {}
destination.mkdir(parents=True)
for path in selected:
    rel = path.relative_to(root)
    target = destination / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    manifest[rel.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
(destination / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(f'Prepared {len(manifest)} files in {destination}')
print('No Git history, clinical reports, credentials, or operational statistics were copied.')
print('Catalog provenance remains subject to DATA_SOURCES.md; this is a release candidate, not publication approval.')
