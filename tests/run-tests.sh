#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
