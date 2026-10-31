import http.client
import importlib.util
import json
import socket
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_cpu_guest_not_counted_twice(self):
        a = collector.parse_cpu_ticks('cpu 100 0 0 100 0 0 0 0 40 0')
        b = collector.parse_cpu_ticks('cpu 150 0 0 150 0 0 0 0 80 0')
        self.assertEqual(collector.cpu_percent(a, b), 50.0)

    def test_docker_size(self):
        self.assertEqual(collector.parse_docker_size('2.132GB'), 2132000000)
        self.assertEqual(collector.parse_docker_size('12.29kB'), 12290)
        self.assertEqual(collector.parse_docker_size('0B'), 0)
        self.assertIsNone(collector.parse_docker_size('N/A'))
        for value in ['.MB', '1..2GB', '1mB']:
            self.assertIsNone(collector.parse_docker_size(value))

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
        self.assertFalse(s.get()['sampling']['healthy'])
        self.assertEqual(s.get()['sampling']['error'], 'OSError')
        s.refresh()
        self.assertEqual(s.get()['host'], {'n': 3})
        self.assertTrue(s.get()['sampling']['healthy'])

    def test_invalid_intervals(self):
        for value in [1, True, None, '15', float('inf'), float('nan'), 3601]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                collector.Sampler(value, dict)

    def test_expiry_uses_monotonic_age_even_without_a_reported_failure(self):
        now = [100.0]
        s = collector.Sampler(15, dict, clock=lambda: now[0])
        s.refresh()
        now[0] = 159.9
        self.assertEqual(s.get()['sampling']['ageSeconds'], 59.9)
        now[0] = 160.0
        with self.assertRaises(collector.SnapshotUnavailable):
            s.get()
        s.refresh()
        self.assertTrue(s.get()['sampling']['healthy'])


class Configuration(unittest.TestCase):
    def test_defaults_and_rejections(self):
        self.assertEqual(collector.validate_config({'envFile': '/opt/qqbot/.env'})['refreshSeconds'], 15)
        for cfg in [[], None, {}, {'envFile': 1}, {'envFile': 'x', 'envKey': 'A=B'},
                    {'envFile': 'x', 'port': 0}, {'envFile': 'x', 'port': True},
                    {'envFile': 'x', 'port': '15090'}, {'envFile': 'x', 'refreshSeconds': float('inf')},
                    {'envFile': 'x', 'bind': '0.0.0.0'}, {'envFile': 'x', 'bind': '8.8.8.8'},
                    {'envFile': 'x', 'bind': '999.1.1.1'}, {'envFile': 'x', 'bind': 'bad interface'}]:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                collector.validate_config(cfg)

    def test_interface_cannot_resolve_to_public_or_wildcard(self):
        for address in ['0.0.0.0', '8.8.8.8']:
            with patch.object(collector, 'run', return_value='1: eth0 inet %s/24' % address):
                with self.assertRaises(ValueError):
                    collector.resolve_bind('eth0')


class DockerPartial(unittest.TestCase):
    def fake(self, args, timeout=6):
        section = 'df' if args[1:3] == ['system', 'df'] else args[1]
        if section == self.failed:
            raise subprocess.CalledProcessError(1, args, stderr='private command output')
        if '-v' in args:
            return '[{"Containers":"1","UniqueSize":"1GB"}]'
        if section == 'df':
            return '{"Type":"Images","Size":"1GB","TotalCount":1,"Reclaimable":"1GB (100%)"}'
        if section == 'ps':
            return '{"Names":"bot","Image":"bot:latest","State":"running"}'
        if section == 'stats':
            return '{"Name":"bot","CPUPerc":"1%","MemUsage":"2MB / 1GB"}'
        return '[{"Name":"/bot","State":{"Running":true,"Status":"running","Health":{"Status":"healthy"}},"RestartCount":2}]'

    def test_each_failure_preserves_other_sections(self):
        for section, key in [('stats', 'stats'), ('inspect', 'inspect'), ('df', 'df'), ('ps', 'containers')]:
            self.failed = section
            with self.subTest(section=section), patch.object(collector, 'run', side_effect=self.fake):
                data = collector.docker()
                self.assertTrue(data['available'])
                self.assertEqual(data['errors'][key], 'CalledProcessError')
                self.assertNotIn('private', json.dumps(data))
                if section != 'ps':
                    self.assertTrue(data['containers'][0]['running'])
                if section != 'df':
                    self.assertEqual(data['df'][0]['reclaimableBytes'], 0)
                if section == 'stats':
                    self.assertEqual(data['containers'][0]['restarts'], 2)
                    self.assertIsNone(data['containers'][0]['cpu'])
                if section == 'inspect':
                    self.assertEqual(data['containers'][0]['cpu'], '1%')
                    self.assertIsNone(data['containers'][0]['restarts'])

    def test_docker_missing_is_unavailable(self):
        with patch.object(collector, 'run', side_effect=FileNotFoundError):
            self.assertFalse(collector.docker()['available'])

    def test_invalid_stats_json_is_isolated(self):
        self.failed = None
        def fake(args, timeout=6):
            return 'invalid json' if args[1] == 'stats' else self.fake(args, timeout)
        with patch.object(collector, 'run', side_effect=fake):
            data = collector.docker()
            self.assertTrue(data['available'])
            self.assertEqual(data['errors']['stats'], 'JSONDecodeError')
            self.assertEqual(data['containers'][0]['health'], 'healthy')


class FakeSnapshot:
    def get(self):
        return {'version': 'test'}


class Http(unittest.TestCase):
    def setUp(self):
        self.server = collector.StatusHTTPServer(('127.0.0.1', 0), collector.make_handler('s' * 64, FakeSnapshot()))
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

    def use_sampler(self, sampler):
        self.server.RequestHandlerClass = collector.make_handler('s' * 64, sampler)

    def test_failure_cache_expiry_and_recovery(self):
        now = [0.0]
        s = collector.Sampler(15, dict, clock=lambda: now[0])
        self.use_sampler(s)
        self.assertEqual(self.get('/healthz'), (503, b'unavailable'))
        self.assertEqual(self.get('/v1/status', 's' * 64)[0], 503)
        s.refresh()
        self.assertEqual(self.get('/healthz'), (200, b'ok'))
        def fail():
            raise OSError('sensitive path')
        s.collect_fn = fail
        s.refresh()
        self.assertEqual(self.get('/healthz'), (503, b'unavailable'))
        code, body = self.get('/v1/status', 's' * 64)
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)['sampling']['healthy'])
        self.assertNotIn(b'sensitive', body)
        now[0] = 60
        self.assertEqual(self.get('/v1/status', 's' * 64)[0], 503)
        self.assertEqual(self.get('/v1/status')[0], 401)
        s.collect_fn = dict
        s.refresh()
        self.assertEqual(self.get('/healthz'), (200, b'ok'))

    def test_idle_connection_expires(self):
        self.server.read_timeout = 0.1
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2) as sock:
            sock.sendall(b'GET /healthz HTTP/1.0\r\n')
            self.assertEqual(sock.recv(1), b'')

    def test_connection_limit_and_slot_reuse(self):
        # Hold every slot without creating 16 threads; excess connections must close.
        for _ in range(self.server.max_connections):
            self.assertTrue(self.server.slots.acquire(blocking=False))
        try:
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2) as sock:
                try:
                    self.assertEqual(sock.recv(1), b'')
                except ConnectionResetError:
                    pass
        finally:
            for _ in range(self.server.max_connections):
                self.server.slots.release()
        self.assertEqual(self.get('/healthz'), (200, b'ok'))

    def test_worker_slot_released_after_response(self):
        for _ in range(self.server.max_connections + 1):
            self.assertEqual(self.get('/healthz'), (200, b'ok'))


if __name__ == '__main__':
    unittest.main()
