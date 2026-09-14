"""Create local configuration without overwriting an existing installation."""
from pathlib import Path
import argparse
import importlib.util
import secrets
import re

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--demo', action='store_true')
parser.add_argument('--source', type=Path, help='Operational VeriSeq source directory')
parser.add_argument('--admin', default='admin@example.com')
parser.add_argument('--port', type=int, default=3000)
args = parser.parse_args()
if (root / '.env').exists():
    parser.error('.env already exists; preserve it or use a fresh release directory')
if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', args.admin):
    parser.error('A valid administrator email is required')
if not 1 <= args.port <= 65535:
    parser.error('Port must be between 1 and 65535')
if args.demo and args.source:
    parser.error('--demo and --source cannot be combined')
if args.demo:
    source = root / '.private/demo-data'
    source.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('demo_generator', root / 'backend/src/veriseq_dashboard/demo.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write_demo_run(source)
    (source / 'DEMO_ONLY.txt').write_text('Entirely invented demonstration reports. Not clinical results.\n')
else:
    if not args.source or not args.source.is_dir():
        parser.error('Provide an existing --source directory or select --demo')
    source = args.source.resolve()
if any(c in str(source) for c in ['\n', '\r', "'", '$']):
    parser.error('Source path contains unsupported environment-file characters')
admin_password = 'A1!' + secrets.token_hex(18)
config = f'''COMPOSE_PROJECT_NAME=veriseq-{'demo' if args.demo else 'lab'}
POSTGRES_PASSWORD={secrets.token_hex(24)}
VERISEQ_INITIAL_ADMIN_EMAIL={args.admin}
VERISEQ_INITIAL_ADMIN_PASSWORD={admin_password}
VERISEQ_HOST_SOURCE_PATH='{source}'
VERISEQ_WEB_PORT={args.port}
VERISEQ_BIND_ADDRESS=127.0.0.1
VERISEQ_ALLOWED_EMAIL_DOMAIN=
VERISEQ_DEMO_MODE={'true' if args.demo else 'false'}
VERISEQ_TIMEZONE=UTC
'''
with (root / '.env').open('x') as file:
    file.write(config)
(root / '.env').chmod(0o600)
print('Created .env with generated credentials. Read the initial administrator password there.')
print('Start: docker compose up --build -d')
print(f'Open: http://localhost:{args.port}')
