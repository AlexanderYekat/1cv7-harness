"""Build the curated, qualified native payload without importing Windows code."""
import hashlib
import json
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


class NativeBuild(build_py):
    def catalog(self):
        return json.loads((ROOT / 'src/harness77/native_catalog77.json').read_text(encoding='utf-8'))

    def get_source_files(self):
        return super().get_source_files() + [str(Path('research') / name) for name in self.catalog()['files']]

    def get_outputs(self, include_bytecode=1):
        payload = Path(self.build_lib) / 'harness77/_native'
        return super().get_outputs(include_bytecode) + [str(payload / name) for name in [*self.catalog()['files'], 'manifest.json']]

    def run(self):
        super().run()
        if self.dry_run:
            return
        payload = Path(self.build_lib) / 'harness77/_native'
        names = self.catalog()['files']
        if payload.exists():
            extra = {p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()} - {*names, 'manifest.json'}
            if extra:
                raise ValueError('stale native build output; use a fresh build directory: ' + str(sorted(extra)))
        hashes = {}
        for name in names:
            source, target = ROOT / 'research' / name, payload / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = {'schema_version': 1, 'runtime_version': self.distribution.get_version(),
                    'platform_version': '7.70.027', 'files': hashes}
        (payload / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


setup(cmdclass={'build_py': NativeBuild})
