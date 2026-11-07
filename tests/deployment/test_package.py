import importlib.util
from pathlib import Path
import subprocess
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('core_package', ROOT / 'scripts/package-source.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def test_archive_excludes_untracked_secrets_symlinks_and_is_deterministic(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init')
    for name in package.FILES | {'service/server.py', 'infrastructure/buildspec.yml', 'scripts/check.py'}:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('sample\n')
    # Even an accidentally tracked .env or symlink must not enter the archive.
    (tmp_path / 'scripts/.env.production').write_text('DO_NOT_SHIP')
    (tmp_path / 'scripts/link.py').symlink_to(tmp_path / 'scripts/check.py')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'fixture')
    (tmp_path / 'scripts/local-secret.txt').write_text('DO_NOT_SHIP')
    first = package.package(tmp_path)
    with ZipFile(first['file']) as archive:
        names = archive.namelist()
        assert 'scripts/check.py' in names
        assert 'scripts/local-secret.txt' not in names
        assert 'scripts/.env.production' not in names
        assert 'scripts/link.py' not in names
    assert package.package(tmp_path)['sha256'] == first['sha256']
    (tmp_path / 'scripts/check.py').write_text('changed\n')
    assert package.package(tmp_path)['sha256'] != first['sha256']
