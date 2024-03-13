"""Hat GUI password conf util"""

import argparse
import hashlib
import secrets
import sys

from hat import json


def create_argument_parser() -> argparse.ArgumentParser:
    """Create argument parser"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--salt', metavar='SALT', default=None)
    parser.add_argument('password', nargs='?', default=None)
    return parser


def main():
    """Main"""
    parser = create_argument_parser()
    args = parser.parse_args()

    password = args.password or sys.stdin.read().strip()
    result = generate(password, args.salt)

    print(json.encode(result))


def generate(password: str,
             salt: str | None = None
             ) -> json.Data:
    """Generate password conf

    Result is defined by ``hat-gui://server.yaml#/$defs/password``

    """
    salt_bytes = salt.encode('utf-8') if salt else secrets.token_bytes(32)
    password_bytes = password.encode('utf-8')
    password_sha256 = hashlib.sha256(password_bytes).digest()
    hash_bytes = hashlib.sha256(salt_bytes + password_sha256).digest()

    return {'hash': hash_bytes.hex(),
            'salt': salt_bytes.hex()}


if __name__ == '__main__':
    sys.argv[0] = 'hat-gui-passwd'
    sys.exit(main())
