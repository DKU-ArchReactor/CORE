"""Create a deterministic archive from allowlisted Git-tracked files only."""
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = {'app', 'service', 'archreactor_contract', 'proto', 'tests', 'scripts', 'infrastructure'}
FILES = {'requirements.txt', 'requirements-server.txt', 'requirements-contract.txt',
         'requirements-deploy.txt', 'requirements-ci.txt', 'Dockerfile.server', '.dockerignore', 'pytest.ini'}


def package(root=ROOT):
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    paths = []
    for name in filter(None, tracked):
        path = Path(name)
        if path.parts[0] not in FOLDERS and name not in FILES:
            continue
        if any(p.startswith('.env') or p in ('.git', '__pycache__') for p in path.parts):
            continue
        source = root / path
        if source.is_symlink() or not source.is_file() or path.suffix in ('.pyc', '.pyo'):
            continue
        if not source.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Archive path escapes checkout: {name}')
        paths.append(name)
    required = FILES | {'service/server.py', 'infrastructure/buildspec.yml'}
    missing = required - set(paths)
    if missing:
        raise ValueError(f'Required files are not tracked: {sorted(missing)}')
    out = root / 'dist/source.zip'
    out.parent.mkdir(exist_ok=True)
    with ZipFile(out, 'w', ZIP_DEFLATED) as archive:
        for name in sorted(paths):
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, (root / name).read_bytes())
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    return {'file': str(out), 'sha256': sha, 'commit': commit,
            'tag': f'core-{commit[:12]}-{sha[:16]}'}


def main():
    print(json.dumps(package()))


if __name__ == '__main__':
    main()
