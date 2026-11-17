"""Start the portable GHS WebGPU site on Windows or a Python 3.9+ host."""
import argparse
import json
import pathlib
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true', help='Local HTTP preview only')
    parser.add_argument('--config', default='server.json')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parent
    if not (root / 'Wasm/index.html').is_file():
        parser.error('Wasm/index.html is missing; extract the entire delivery archive first.')
    command = [sys.executable, '-I', '-B', str(root / 'serve.py'), '--root', str(root / 'Wasm')]
    if args.local:
        port = args.port if args.port is not None else 8800
        command += ['--bind', '127.0.0.1', '--port', str(port), '--open', 'index.html']
        address = f'http://127.0.0.1:{port}/'
    else:
        config_path = pathlib.Path(args.config)
        if not config_path.is_absolute():
            config_path = root / config_path
        try:
            config = json.loads(config_path.read_text(encoding='utf-8-sig'))
            port = args.port if args.port is not None else int(config.get('port', 8800))
            hosts = config['allowed_hosts']
            cert = root / config['certificate']
            key = root / config['private_key']
            if not isinstance(hosts, list) or not hosts or not all(isinstance(h, str) and h for h in hosts):
                raise ValueError('allowed_hosts must contain your server DNS name or IP')
            if not cert.is_file() or not key.is_file():
                raise ValueError('TLS files not found. Set certificate/private_key in server.json first.')
            command += ['--bind', config.get('bind', '0.0.0.0'), '--port', str(port),
                        '--tls-cert', str(cert), '--tls-key', str(key)]
            for host in hosts:
                command += ['--allow-host', host]
            address = f'https://{hosts[0]}:{port}/'
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(str(error))
    if not 1 <= port <= 65535:
        parser.error('port must be between 1 and 65535')
    print(f'GHS warehouse: {address}', flush=True)
    print('Keep this window open. Ctrl+C stops the server.', flush=True)
    try:
        return subprocess.call(command, cwd=root)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
