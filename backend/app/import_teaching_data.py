"""UTF-8 stdin CLI for explicit teaching dataset migration/import/verification."""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from .teaching_payload import validate_payload
from .teaching_store import import_dataset, verify_database


def _connect():
    password = os.environ['POSTGRES_PASSWORD']
    if not password.strip() or password == 'CHANGE_ME':
        raise ValueError('Unconfigured password.')
    return psycopg.connect(host=os.environ.get('PGHOST', 'db'), port=int(os.environ.get('PGPORT', 5432)),
                           dbname=os.environ.get('POSTGRES_DB', 'flood'), user=os.environ['POSTGRES_USER'],
                           password=password, connect_timeout=2, autocommit=True,
                           options='-c statement_timeout=30000 -c lock_timeout=5000',
                           application_name='urban-flood-teaching-import')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field.')
        result[key] = value
    return result


def main(argv=None, stdin=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        text = (stdin or sys.stdin).read(8_000_001)
        if len(text) > 8_000_000:
            raise ValueError('Teaching payload too large.')
        payload = json.loads(text, object_pairs_hook=_unique_object)
        validate_payload(payload)
        with _connect() as connection:
            if args.verify_only:
                with connection.transaction():
                    connection.execute('SET TRANSACTION READ ONLY')
                    result = verify_database(connection, payload)
            else:
                result = import_dataset(connection, payload, Path('/app/migrations/010_teaching_data.sql'))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, psycopg.Error, UnicodeError):
        print(json.dumps({'status': 'error', 'detail': 'teaching data operation failed; check data contract and database availability'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
