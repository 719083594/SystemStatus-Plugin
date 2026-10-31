import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build-release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Release(unittest.TestCase):
    def test_combined_package_matches_source_and_contains_no_instance_files(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = builder.build(temp)
            version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
            root = 'SystemStatus-Plugin-v%s/' % version
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len(z.namelist()), 18)
                self.assertIn(root + 'collector/collector.py', z.namelist())
                self.assertIn(root + 'collector/qqbot-system-status.service', z.namelist())
                self.assertIn(root + 'plugin/SystemStatus-Plugin/index.js', z.namelist())
                for name in z.namelist():
                    relative = name.removeprefix(root).removeprefix('plugin/SystemStatus-Plugin/')
                    self.assertEqual(z.read(name), (ROOT / relative).read_bytes(), name)
                    self.assertFalse(any(part in {'.env', 'node_modules', '__pycache__', 'tests', '.git'} for part in Path(name).parts))
                    self.assertFalse(name.endswith('/config.json'))
            expected = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual((Path(temp) / 'SHA256SUMS.txt').read_text().split()[0], expected)
            first = archive.read_bytes()
            self.assertEqual(builder.build(temp).read_bytes(), first)
