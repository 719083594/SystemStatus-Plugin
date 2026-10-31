#!/usr/bin/env python3
"""SystemStatus collector: reports host and Docker status over a token-protected local HTTP API.

Runs on the host (not in a container). Standard library only. It never changes anything on the host.
Waits refreshSeconds (default 15) after each background collection and serves a bounded-age snapshot.
GET /v1/status  -> JSON snapshot (Authorization: Bearer <token>)
GET /healthz    -> "ok" / 503 "unavailable" (no auth, no host data)
"""
import argparse, hmac, ipaddress, json, math, os, re, socket, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = '3.0.2'
DISK_TYPES = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs'}
CONTAINER_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')


def read_env_value(path, key):
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return ''


def resolve_bind(value):
    """Resolve a private/loopback IPv4 literal or a network interface name."""
    if re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', value):
        return private_ipv4(value)
    out = run(['ip', '-4', '-o', 'addr', 'show', 'dev', value], 5)
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/', out)
    if not match:
        raise SystemExit('No IPv4 address on interface %s' % value)
    return private_ipv4(match.group(1))


def private_ipv4(value):
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_multicast or address.is_reserved or not address.is_private:
        raise ValueError('bind must be a private or loopback IPv4 address')
    return str(address)


def validate_interval(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 5 <= value <= 3600:
        raise ValueError('refreshSeconds must be a finite number from 5 to 3600')
    return float(value)


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError('config must be an object')
    cfg = dict(bind='docker0', port=15090, envKey='SYSTEM_STATUS_TOKEN', refreshSeconds=15)
    cfg.update(value)
    if not isinstance(cfg.get('envFile'), str) or not cfg['envFile'].strip():
        raise ValueError('envFile must be a nonempty path')
    if not isinstance(cfg['envKey'], str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg['envKey']):
        raise ValueError('envKey must be an environment variable name')
    if type(cfg['port']) is not int or not 1 <= cfg['port'] <= 65535:
        raise ValueError('port must be an integer from 1 to 65535')
    bind = cfg['bind']
    if not isinstance(bind, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', bind):
        raise ValueError('bind must be an IPv4 address or interface name')
    if re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}', bind):
        private_ipv4(bind)
    cfg['refreshSeconds'] = validate_interval(cfg['refreshSeconds'])
    return cfg


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
    # guest/guest_nice are already included in user/nice by the Linux kernel.
    return sum(values[:8]), idle


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
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(B|kB|KB|MB|GB|TB)\s*', str(text or ''))
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
    errors = {}

    def query(section, args, parser, timeout=6):
        try:
            return parser(run(args, timeout))
        except Exception as e:
            # Only expose exception types, never raw CLI output or host configuration.
            errors[section] = e.__class__.__name__
            return None

    def objects(text):
        rows = [json.loads(line) for line in text.splitlines() if line]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError('expected Docker objects')
        return rows

    df = query('df', ['docker', 'system', 'df', '--format', '{{json .}}'], objects)
    images = None
    if df is not None:
        images = query('images', ['docker', 'system', 'df', '-v', '--format', '{{json .Images}}'],
                       lambda text: unused_images(json.loads(text or '[]')), 15)
    listed = query('containers', ['docker', 'ps', '-a', '--format', '{{json .}}'], objects)
    selected = [row for row in (listed or []) if CONTAINER_NAME.fullmatch(str(row.get('Names', '')))][:50]
    names = [row['Names'] for row in selected]
    stats, details = {}, {}
    if names:
        sampled = query('stats', ['docker', 'stats', '--no-stream', '--format', '{{json .}}', *names], objects, 15)
        stats = {row.get('Name'): row for row in (sampled or [])}

        def inspect(text):
            rows = json.loads(text)
            if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get('Name'), str) for row in rows):
                raise ValueError('expected container details')
            return {row['Name'].lstrip('/'): row for row in rows}

        details = query('inspect', ['docker', 'inspect', *names], inspect) or {}
    containers = []
    for row in selected:
        name = row['Names']
        c, s = details.get(name, {}), stats.get(name, {})
        state = c.get('State') or {}
        status = state.get('Status', row.get('State', 'unknown'))
        running = state.get('Running')
        if not isinstance(running, bool):
            running = (status == 'running') if status in {'created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead'} else None
        containers.append({'name': name, 'image': (c.get('Config') or {}).get('Image', row.get('Image', '')),
                           'running': running, 'status': status,
                           'health': (state.get('Health') or {}).get('Status'),
                           'restarts': c.get('RestartCount'), 'startedAt': state.get('StartedAt'),
                           'cpu': s.get('CPUPerc'), 'memory': s.get('MemUsage')})
    rows = []
    for d in df or []:
        row = {'type': d.get('Type'), 'size': d.get('Size'), 'reclaimable': d.get('Reclaimable'),
               'total': d.get('TotalCount'), 'active': d.get('Active')}
        if d.get('Type') == 'Images':
            # Never pass Docker's own image figure on: it claims in-use images are removable.
            row.pop('reclaimable')
            if images is not None:
                row.update(images)
        rows.append(row)
    return {'available': df is not None or listed is not None, 'df': rows, 'containers': containers,
            'errors': errors, 'truncated': len(listed or []) > 50}


def collect():
    return {'host': host(), 'docker': docker()}


class SnapshotUnavailable(RuntimeError):
    pass


class Sampler:
    """Collects in the background every `interval` seconds; requests get the latest snapshot instantly.

    docker stats alone takes about 2 s, so collecting on demand would make every command wait for it.
    """

    def __init__(self, interval, collect_fn=collect, clock=time.monotonic):
        self.interval, self.collect_fn = validate_interval(interval), collect_fn
        self.lock, self.value, self.error = threading.Lock(), None, None
        self.clock, self.completed_at = clock, None
        self.max_age = max(60.0, 3 * self.interval)

    def refresh(self):
        try:
            data = self.collect_fn()
            data.update(version=VERSION, collectedAt=int(time.time() * 1000), refreshSeconds=self.interval)
        except Exception as e:  # retain recent cache, but mark the failure and expire it
            with self.lock:
                self.error = e.__class__.__name__
            return
        with self.lock:
            self.value, self.error = data, None
            self.completed_at = self.clock()

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
            if self.value is None or self.clock() - self.completed_at >= self.max_age:
                raise SnapshotUnavailable('snapshot unavailable or expired')
            return dict(self.value, sampling={'healthy': self.error is None, 'error': self.error,
                                             'ageSeconds': round(max(0, self.clock() - self.completed_at), 1),
                                             'maxAgeSeconds': self.max_age})


class StatusHTTPServer(ThreadingHTTPServer):
    """Bound concurrent connections and idle header/read time, including unauthenticated peers."""
    max_connections = 16
    request_queue_size = 16
    read_timeout = 5

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.read_timeout)
        return request, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


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
                try:
                    healthy = snapshot.get().get('sampling', {}).get('healthy', True)
                except Exception:
                    healthy = False
                return self.send(200 if healthy else 503, b'ok' if healthy else b'unavailable', 'text/plain')
            if self.path != '/v1/status':
                return self.send(404, {'error': 'not found'})
            given = self.headers.get('Authorization', '')
            if not hmac.compare_digest(given.encode(), ('Bearer ' + token).encode()):
                return self.send(401, {'error': 'unauthorized'})
            try:
                return self.send(200, snapshot.get())
            except SnapshotUnavailable:
                return self.send(503, {'error': 'snapshot unavailable or expired'})
            except Exception as e:
                return self.send(500, {'error': e.__class__.__name__})

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()
    cfg = validate_config(json.loads(Path(args.config).read_text(encoding='utf-8')))
    token = read_env_value(cfg['envFile'], cfg.get('envKey', 'SYSTEM_STATUS_TOKEN'))
    if len(token) < 32:
        raise SystemExit('Token missing or shorter than 32 characters in %s' % cfg['envFile'])
    address = resolve_bind(cfg.get('bind', 'docker0'))
    sampler = Sampler(cfg.get('refreshSeconds', 15)).start()
    server = StatusHTTPServer((address, cfg['port']), make_handler(token, sampler))
    print('SystemStatus collector %s listening on %s:%s' % (VERSION, address, server.server_port), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
