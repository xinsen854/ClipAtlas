from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from clipatlas.catalog.legacy_import import import_legacy_annotations


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_db", type=Path)
    parser.add_argument("target_db", type=Path)
    args = parser.parse_args()
    report = import_legacy_annotations(args.source_db, args.target_db)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
