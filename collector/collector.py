#!/usr/bin/env python3
"""SystemStatus collector: reports host and Docker status over a token-protected local HTTP API.

Runs on the host (not in a container). Standard library only. It never changes anything on the host.
Collects in the background every refreshSeconds (default 15) and answers with the latest snapshot.
GET /v1/status  -> JSON snapshot (Authorization: Bearer <token>)
GET /healthz    -> "ok" (no auth, no data)
"""
import argparse, hmac, json, os, re, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = '3.0.0'
DISK_TYPES = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs'}
CONTAINER_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')


def read_env_value(path, key):
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return ''


def resolve_bind(value):
    """An IPv4 address is used as is; anything else is treated as a network interface name."""
    if re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', value):
        return value
    out = subprocess.run(['ip', '-4', '-o', 'addr', 'show', 'dev', value], capture_output=True, text=True, timeout=5).stdout
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/', out)
    if not match:
        raise SystemExit('No IPv4 address on interface %s' % value)
    return match.group(1)


def run(args, timeout=6):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True).stdout


# ---- host metrics (pure readers, testable with fixture text) ----

def parse_meminfo(text):
    fields = {}
    for line in text.splitlines():
        name, _, rest = line.partition(':')
        parts = rest.split()
        if parts:
            fields[name] = int(parts[0]) * 1024
    total = fields.get('MemTotal', 0)
    available = fields.get('MemAvailable', fields.get('MemFree', 0))
    swap_total = fields.get('SwapTotal', 0)
    return {'total': total, 'used': total - available, 'available': available,
            'swapTotal': swap_total, 'swapUsed': swap_total - fields.get('SwapFree', 0)}


def parse_cpu_ticks(text):
    values = [int(v) for v in text.splitlines()[0].split()[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent(first, second):
    total, idle = second[0] - first[0], second[1] - first[1]
    return round((total - idle) / total * 100, 1) if total > 0 else 0.0


def os_name():
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if line.startswith('PRETTY_NAME='):
                return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return 'Linux'


def disks():
    result, seen = [], set()
    for line in Path('/proc/mounts').read_text().splitlines():
        source, mount, kind, *_ = line.split()
        if kind not in DISK_TYPES:
            continue
        mount = mount.replace('\\040', ' ')
        try:
            dev = os.stat(mount).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            v = os.statvfs(mount)
        except OSError:
            continue
        total, available = v.f_blocks * v.f_frsize, v.f_bavail * v.f_frsize
        result.append({'mount': mount, 'type': kind, 'total': total, 'used': total - v.f_bfree * v.f_frsize,
                       'available': available})
    return result


def host():
    first = parse_cpu_ticks(Path('/proc/stat').read_text())
    time.sleep(0.5)
    second = parse_cpu_ticks(Path('/proc/stat').read_text())
    load = Path('/proc/loadavg').read_text().split()[:3]
    return {'hostname': socket.gethostname(), 'os': os_name(), 'kernel': os.uname().release,
            'uptime': float(Path('/proc/uptime').read_text().split()[0]),
            'cores': os.cpu_count() or 1, 'cpuPercent': cpu_percent(first, second),
            'load': [float(x) for x in load], 'memory': parse_meminfo(Path('/proc/meminfo').read_text()),
            'disks': disks()}


# ---- docker (read-only CLI calls) ----

DOCKER_UNITS = {'B': 1, 'kB': 1e3, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9, 'TB': 1e12}


def parse_docker_size(text):
    """Docker prints decimal units, e.g. '2.132GB'. Returns bytes, or None when unreadable."""
    match = re.fullmatch(r'\s*([\d.]+)\s*([kKMGT]?B)\s*', str(text or ''))
    return int(float(match.group(1)) * DOCKER_UNITS[match.group(2)]) if match else None


def unused_images(images):
    """Images used by no container at all (running or stopped): what `docker image prune -a` could remove.

    `docker system df` reports every image as 100% reclaimable on this Docker version even while all are in use,
    so the figure is computed from the per-image container count instead. Unknown counts are treated as in use.
    """
    unused = [i for i in images if str(i.get('Containers', '')).strip() == '0']
    sizes = [parse_docker_size(i.get('UniqueSize') or i.get('Size')) for i in unused]
    return {'unusedCount': len(unused), 'reclaimableBytes': sum(s for s in sizes if s is not None)}


def docker():
    try:
        df = [json.loads(line) for line in run(['docker', 'system', 'df', '--format', '{{json .}}']).splitlines() if line]
        try:
            images = unused_images(json.loads(run(['docker', 'system', 'df', '-v', '--format', '{{json .Images}}'], 15) or '[]'))
        except Exception:
            images = None
        names = [n for n in run(['docker', 'ps', '-a', '--format', '{{.Names}}']).splitlines() if CONTAINER_NAME.match(n)][:50]
        containers = []
        if names:
            stats = {}
            for line in run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *names], 15).splitlines():
                if line:
                    s = json.loads(line)
                    stats[s.get('Name')] = s
            for c in json.loads(run(['docker', 'inspect', *names])):
                name = c['Name'].lstrip('/')
                s = stats.get(name, {})
                state = c.get('State', {})
                containers.append({'name': name, 'image': c.get('Config', {}).get('Image', ''),
                                   'running': bool(state.get('Running')), 'status': state.get('Status', ''),
                                   'health': (state.get('Health') or {}).get('Status'),
                                   'restarts': c.get('RestartCount', 0), 'startedAt': state.get('StartedAt'),
                                   'cpu': s.get('CPUPerc'), 'memory': s.get('MemUsage')})
        rows = []
        for d in df:
            row = {'type': d.get('Type'), 'size': d.get('Size'), 'reclaimable': d.get('Reclaimable'),
                   'total': d.get('TotalCount'), 'active': d.get('Active')}
            if d.get('Type') == 'Images':
                # Never pass Docker's own image figure on: it claims in-use images are removable.
                row.pop('reclaimable')
                if images:
                    row.update(images)
            rows.append(row)
        return {'available': True, 'df': rows, 'containers': containers}
    except Exception as e:
        return {'available': False, 'error': e.__class__.__name__}


def collect():
    return {'host': host(), 'docker': docker()}


class Sampler:
    """Collects in the background every `interval` seconds; requests get the latest snapshot instantly.

    docker stats alone takes about 2 s, so collecting on demand would make every command wait for it.
    """

    def __init__(self, interval, collect_fn=collect):
        self.interval, self.collect_fn = max(5.0, float(interval)), collect_fn
        self.lock, self.value, self.error = threading.Lock(), None, None

    def refresh(self):
        try:
            data = self.collect_fn()
        except Exception as e:  # keep serving the last good snapshot
            with self.lock:
                self.error = e.__class__.__name__
            return
        data.update(version=VERSION, collectedAt=int(time.time() * 1000), refreshSeconds=self.interval)
        with self.lock:
            self.value, self.error = data, None

    def start(self):
        self.refresh()  # first snapshot before the server accepts requests

        def loop():
            while True:
                time.sleep(self.interval)
                self.refresh()

        threading.Thread(target=loop, name='sampler', daemon=True).start()
        return self

    def get(self):
        with self.lock:
            if self.value is None:
                raise RuntimeError(self.error or 'no snapshot yet')
            return self.value


def make_handler(token, snapshot):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'SystemStatus/' + VERSION

        def log_message(self, fmt, *args):
            pass

        def send(self, code, body, kind='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/healthz':
                return self.send(200, b'ok', 'text/plain')
            if self.path != '/v1/status':
                return self.send(404, {'error': 'not found'})
            given = self.headers.get('Authorization', '')
            if not hmac.compare_digest(given.encode(), ('Bearer ' + token).encode()):
                return self.send(401, {'error': 'unauthorized'})
            try:
                return self.send(200, snapshot.get())
            except Exception as e:
                return self.send(500, {'error': e.__class__.__name__})

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8'))
    token = read_env_value(cfg['envFile'], cfg.get('envKey', 'SYSTEM_STATUS_TOKEN'))
    if len(token) < 32:
        raise SystemExit('Token missing or shorter than 32 characters in %s' % cfg['envFile'])
    address = resolve_bind(cfg.get('bind', 'docker0'))
    sampler = Sampler(cfg.get('refreshSeconds', 15)).start()
    server = ThreadingHTTPServer((address, int(cfg.get('port', 15090))), make_handler(token, sampler))
    print('SystemStatus collector %s listening on %s:%s' % (VERSION, address, server.server_port), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
