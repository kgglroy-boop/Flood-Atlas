"""Offline CLI; errors are concise and successful output is machine-readable JSON."""

import argparse
import json
from pathlib import Path

from .artifacts import generate_dataset
from .contract import load_contract
from .validation import validate_dataset


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    generate = sub.add_parser('generate')
    generate.add_argument('--contract', type=Path, required=True)
    generate.add_argument('--output-root', type=Path, required=True)
    generate.add_argument('--sources', type=Path, required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('--contract', type=Path, required=True)
    verify.add_argument('--dataset-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'generate':
            directory = generate_dataset(args.contract, args.output_root, args.sources)
            result = {'status': 'ok', 'dataset_dir': str(directory), 'generation_id': directory.name}
        else:
            result = validate_dataset(args.dataset_dir, load_contract(args.contract))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({'status': 'error', 'detail': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
