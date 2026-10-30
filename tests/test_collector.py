import http.client
import importlib.util
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location('collector', Path(__file__).resolve().parent.parent / 'collector' / 'collector.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

MEMINFO = """MemTotal:        7765000 kB
MemFree:          500000 kB
MemAvailable:    6500000 kB
SwapTotal:       2097148 kB
SwapFree:        2097000 kB
"""


class Parsing(unittest.TestCase):
    def test_meminfo(self):
        m = collector.parse_meminfo(MEMINFO)
        self.assertEqual(m['total'], 7765000 * 1024)
        self.assertEqual(m['used'], (7765000 - 6500000) * 1024)
        self.assertEqual(m['swapUsed'], 148 * 1024)

    def test_cpu(self):
        a = collector.parse_cpu_ticks('cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3')
        b = collector.parse_cpu_ticks('cpu  150 0 150 850 0 0 0 0 0 0\ncpu0 1 2 3')
        self.assertEqual(collector.cpu_percent(a, b), 66.7)
        self.assertEqual(collector.cpu_percent(a, a), 0.0)

    def test_docker_size(self):
        self.assertEqual(collector.parse_docker_size('2.132GB'), 2132000000)
        self.assertEqual(collector.parse_docker_size('12.29kB'), 12290)
        self.assertEqual(collector.parse_docker_size('0B'), 0)
        self.assertIsNone(collector.parse_docker_size('N/A'))

    def test_unused_images_ignore_docker_claim(self):
        images = [{'Containers': '1', 'UniqueSize': '2.132GB'}, {'Containers': '1', 'UniqueSize': '2.162GB'},
                  {'Containers': '0', 'UniqueSize': '150MB'}, {'Containers': 'N/A', 'UniqueSize': '9GB'}]
        self.assertEqual(collector.unused_images(images), {'unusedCount': 1, 'reclaimableBytes': 150000000})
        self.assertEqual(collector.unused_images(images[:2]), {'unusedCount': 0, 'reclaimableBytes': 0})

    def test_bind_accepts_ip(self):
        self.assertEqual(collector.resolve_bind('127.0.0.1'), '127.0.0.1')

    def test_read_env_value(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.env') as f:
            f.write('A=1\nSYSTEM_STATUS_TOKEN=abc\n')
        try:
            self.assertEqual(collector.read_env_value(f.name, 'SYSTEM_STATUS_TOKEN'), 'abc')
            self.assertEqual(collector.read_env_value(f.name, 'MISSING'), '')
        finally:
            os.unlink(f.name)


class SamplerTest(unittest.TestCase):
    def test_serves_latest_and_keeps_last_good(self):
        calls = []

        def fake():
            calls.append(1)
            if len(calls) == 2:
                raise OSError('docker down')
            return {'host': {'n': len(calls)}, 'docker': {}}

        s = collector.Sampler(15, fake)
        with self.assertRaises(RuntimeError):
            s.get()
        s.refresh()
        first = s.get()
        self.assertEqual(first['host'], {'n': 1})
        self.assertEqual(first['refreshSeconds'], 15.0)
        self.assertIn('collectedAt', first)
        s.refresh()  # fails: the previous snapshot stays available
        self.assertEqual(s.get()['host'], {'n': 1})
        s.refresh()
        self.assertEqual(s.get()['host'], {'n': 3})

    def test_interval_has_a_floor(self):
        self.assertEqual(collector.Sampler(1, dict).interval, 5.0)


class FakeSnapshot:
    def get(self):
        return {'version': 'test'}


class Http(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), collector.make_handler('s' * 64, FakeSnapshot()))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path, token=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        c.request('GET', path, headers={'Authorization': 'Bearer ' + token} if token else {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def test_health_needs_no_token(self):
        self.assertEqual(self.get('/healthz'), (200, b'ok'))

    def test_status_requires_token(self):
        self.assertEqual(self.get('/v1/status')[0], 401)
        self.assertEqual(self.get('/v1/status', 'wrong')[0], 401)
        status, body = self.get('/v1/status', 's' * 64)
        self.assertEqual(status, 200)
        self.assertIn(b'"version": "test"', body)

    def test_unknown_path(self):
        self.assertEqual(self.get('/etc/passwd', 's' * 64)[0], 404)


if __name__ == '__main__':
    unittest.main()
