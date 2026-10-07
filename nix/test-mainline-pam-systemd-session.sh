#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

exec nix build --no-link "$ROOT#checks.x86_64-linux.ssh"
