#!/usr/bin/env python3
"""Windows-friendly local setup, credential checks, and interview commands."""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-f', 'compose.yaml', '-f', 'compose.postman.yaml']
MANAGED = set(re.findall(r'^([A-Z][A-Z0-9_]*)=', (ROOT / '.env.example').read_text(), re.M))


def docker(*args, capture=False, check=True):
    # The project's .env is authoritative; old PowerShell exports must not shadow it.
    child_env = {key: value for key, value in os.environ.items() if key not in MANAGED}
    result = subprocess.run([*COMPOSE, *args], cwd=ROOT, env=child_env,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, text=True, encoding='utf-8', errors='replace')
    if check and result.returncode:
        raise RuntimeError('Docker failed: ' + ' '.join(args[:3]) + ('. ' + result.stderr.strip() if capture else ''))
    return result


def read_settings():
    path = ROOT / '.env'
    values = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$', line)
            if match:
                value = match[2]
                if len(value) > 1 and value[0] == value[-1] == "'":
                    value = value[1:-1].replace("\\'", "'")
                elif len(value) > 1 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                values[match[1]] = value
    return values


def write_settings(values):
    path = ROOT / '.env'
    existing = path.read_text(encoding='utf-8-sig') if path.exists() else (ROOT / '.env.example').read_text()
    for key, value in values.items():
        if '\n' in value or '\r' in value or '\x00' in value:
            raise RuntimeError(f'{key} cannot contain newlines or null characters.')
        line = key + "='" + value.replace("'", "\\'") + "'"
        pattern = r'(?m)^\s*(?:export\s+)?' + re.escape(key) + r'\s*=[^\r\n]*'
        existing = re.sub(pattern, lambda _: line, existing) if re.search(pattern, existing) else existing.rstrip() + '\n' + line + '\n'
    path.write_text(existing, encoding='utf-8')
    path.chmod(0o600)


def container_settings(service):
    result = docker('ps', '-a', '-q', service, capture=True, check=False)
    ids = result.stdout.splitlines()
    if not ids:
        return {}
    inspected = subprocess.run(['docker', 'inspect', ids[0]], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if inspected.returncode:
        return {}
    return dict(item.split('=', 1) for item in json.loads(inspected.stdout)[0]['Config']['Env'] if '=' in item)


def valid_key(value, prefix=False):
    try:
        if prefix:
            if not value.startswith('base64:'):
                return False
            value = value[7:]
        length = len(base64.b64decode(value, validate=True))
        return length == 32 if prefix else length >= 32
    except (ValueError, TypeError):
        return False


def initialize():
    values = read_settings()
    current_api = container_settings('api')
    current_db = container_settings('postgres')
    current_inventory = container_settings('warehouse-db')
    defaults = {'API_PORT': '8080', 'POSTGRES_PORT': '5433', 'POSTGRES_DB': current_db.get('POSTGRES_DB', 'shop_laravel'),
                'POSTGRES_USER': current_db.get('POSTGRES_USER', 'shop'),
                'POSTGRES_PASSWORD': current_db.get('POSTGRES_PASSWORD', secrets.token_urlsafe(24)),
                'WAREHOUSE_POSTGRES_PASSWORD': current_inventory.get('POSTGRES_PASSWORD', secrets.token_urlsafe(24)),
                'ADMIN_EMAIL': current_api.get('ADMIN_EMAIL', 'admin@shop.local'), 'LOGIN_RATE_LIMIT_PERMIT_LIMIT': '5',
                'FRONTEND_ORIGIN': 'http://localhost:5173'}
    for key, value in defaults.items():
        if not values.get(key):
            values[key] = value
    for key, prefix in [('APP_KEY', True), ('JWT_SIGNING_KEY', False)]:
        if not valid_key(values.get(key, ''), prefix):
            restored = current_api.get(key, '')
            values[key] = restored if valid_key(restored, prefix) else ('base64:' if prefix else '') + base64.b64encode(secrets.token_bytes(32)).decode()
    if not values.get('ADMIN_PASSWORD'):
        values['ADMIN_PASSWORD'] = current_api.get('ADMIN_PASSWORD', '')
    if not values['ADMIN_PASSWORD']:
        values['ADMIN_PASSWORD'] = getpass.getpass('Set the admin password (or enter the existing database admin password): ')
    if not 8 <= len(values['ADMIN_PASSWORD'].encode()) <= 72:
        raise RuntimeError('Admin password must contain 8 to 72 bytes.')
    write_settings(values)
    return values


def addresses():
    http = docker('port', 'api', '80', capture=True).stdout.strip().splitlines()[0]
    grpc = docker('port', 'warehouse', '50051', capture=True).stdout.strip().splitlines()[0]
    return 'http://127.0.0.1:' + http.rsplit(':', 1)[1], int(grpc.rsplit(':', 1)[1])


def prepare(values):
    from prepare_demo import DemoHttpError, prepare as generate
    base, grpc = addresses()
    warehouse = [*COMPOSE, 'exec', '-T', 'warehouse', '/usr/local/bin/warehouse']
    # Stock seeding uses Docker subprocesses; clear stale inherited overrides there too.
    for key in MANAGED:
        os.environ.pop(key, None)
    email, password = values['ADMIN_EMAIL'], values['ADMIN_PASSWORD']
    try:
        generate(base, grpc, email, password, warehouse)
    except DemoHttpError as error:
        if error.status != 401:
            raise
        print('The saved admin password was not accepted. Existing database users keep their original password.\n'
              'If the account was locked after repeated failures, wait five minutes before retrying.', flush=True)
        password = getpass.getpass('Enter the admin password that works in the browser: ')
        generate(base, grpc, email, password, warehouse)
        write_settings({'ADMIN_PASSWORD': password})
    print(f'\nREADY: {base}\nAPI documentation: {base}/docs\ngRPC server: 127.0.0.1:{grpc}\n'
          f'Postman files: {ROOT / "Postman-Ready"}\nAdmin email: {email}\n'
          'The ready collections work with No environment. Keep Postman-Ready private.\n'
          'Wait 60 seconds between collection runs if login protection returns HTTP 429.', flush=True)
    return base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'prepare', 'race', 'stop'])
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--prepared', type=Path)
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 10):
            raise RuntimeError('Python 3.10 or later is required.')
        if args.action == 'stop':
            docker('stop')
            print('All services stopped. Database and image volumes retained.')
            return 0
        if args.action == 'race':
            from concurrent_checkout import LoginFailure, execute, prepare_race
            base, _ = addresses()
            for key, value in read_settings().items():
                if key in ('ADMIN_EMAIL', 'ADMIN_PASSWORD'):
                    os.environ[key] = value
            if args.prepared:
                execute(base, args.prepared)
            else:
                try:
                    path = prepare_race(base)
                except LoginFailure as error:
                    if error.status != 401:
                        raise
                    print('The configured admin password differs from the existing database password.', flush=True)
                    password = getpass.getpass('Enter the admin password that works in the browser: ')
                    os.environ['ADMIN_PASSWORD'] = password
                    path = prepare_race(base)
                    write_settings({'ADMIN_PASSWORD': password})
                if not args.prepare_only:
                    execute(base, path)
            return 0
        if args.action == 'start':
            subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], check=True, timeout=25)
            values = initialize()
            docker('config', '--quiet')
            if not args.skip_build:
                docker('build', 'api', 'warehouse')
            result = docker('up', '-d', '--no-build', '--wait', '--wait-timeout', '180', check=False)
            if result.returncode:
                docker('logs', '--no-color', '--tail', '40', 'api', 'warehouse', check=False)
                raise RuntimeError('Docker startup failed; inspect the service log above.')
            docker('ps')
            probe = 'foreach ([50051,50052] as $port) { $s=@fsockopen("warehouse",$port,$e,$m,3); if (!$s) {fwrite(STDERR,"warehouse:$port unavailable\\n");exit(1);} fclose($s); echo "warehouse:$port CONNECTED\\n"; }'
            docker('exec', '-T', 'api', 'php', '-r', probe)
        else:
            values = read_settings()
            if not values.get('ADMIN_EMAIL') or not values.get('ADMIN_PASSWORD'):
                raise RuntimeError('Run Start-Shop.ps1 once to configure the local .env file.')
        base = prepare(values)
        if not args.no_browser:
            webbrowser.open(base)
            if os.name == 'nt':
                os.startfile(str(ROOT / 'Postman-Ready'))
        return 0
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nCancelled. Existing database volumes were retained.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
