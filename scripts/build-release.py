#!/usr/bin/env python3
"""Build a combined plugin + host collector package from an explicit allowlist."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def build(output):
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    if json.loads((ROOT / 'plugin.manifest.json').read_text(encoding='utf-8'))['version'] != version:
        raise ValueError('plugin version mismatch')
    tree = ast.parse((ROOT / 'collector/collector.py').read_text(encoding='utf-8'))
    collector_version = next(ast.literal_eval(node.value) for node in tree.body
                             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets))
    if collector_version != version:
        raise ValueError('collector version mismatch')
    notes = 'docs/RELEASE_NOTES_%s.md' % version.replace('.', '_')
    prefix = 'SystemStatus-Plugin-v%s/' % version
    files = {}

    def add(source, destination):
        path = ROOT / source
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('invalid release input: ' + source)
        files[prefix + destination] = path

    for name in ['README.md', 'LICENSE', notes, 'docs/MIGRATION_2_TO_3.md']:
        add(name, name)
    for name in ['index.js', 'package.json', 'plugin.manifest.json', 'LICENSE', 'config/defaults.json',
                 'resources/status.html', 'lib/command.mjs', 'lib/config.mjs', 'lib/client.mjs',
                 'lib/html.mjs', 'lib/format.mjs']:
        add(name, 'plugin/SystemStatus-Plugin/' + name)
    for name in ['collector.py', 'config.example.json', 'qqbot-system-status.service']:
        add('collector/' + name, 'collector/' + name)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ('SystemStatus-Plugin-v%s.zip' % version)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, source in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            z.writestr(entry, source.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text('%s  %s\n' % (digest, archive.name), encoding='utf-8')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.output))
