#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
if [[ $# != 1 || ! -f $1/include/uapi/linux/v4l2-controls.h ]]; then
  echo "Usage: $0 KERNEL_SOURCE (native compiler in CC)" >&2
  exit 2
fi
source_dir=$(cd -- "$(dirname -- "$0")" && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
mkdir -p "$test_dir/include/linux"
# Use the target control ABI with the host's exported Linux integer types.
# Adding the entire unexported kernel UAPI directory is not a host build API.
cp "$1/include/uapi/linux/v4l2-controls.h" "$test_dir/include/linux/"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -I "$test_dir/include" "$source_dir/mt6797-h264-controls.c" \
  "$source_dir/test-mt6797-h264-controls.c" -o "$test_dir/test"
"$test_dir/test"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -I "$test_dir/include" "$source_dir/mt6797-h264-controls.c" \
  "$source_dir/test-mt6797-h264-weights.c" -o "$test_dir/test-weights"
"$test_dir/test-weights"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -I "$test_dir/include" "$source_dir/mt6797-h264-controls.c" \
  "$source_dir/test-mt6797-h264-references.c" -o "$test_dir/test-references"
"$test_dir/test-references"
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -I "$test_dir/include" "$source_dir/mt6797-h264-controls.c" \
  "$source_dir/test-mt6797-h264-slices.c" -o "$test_dir/test-slices"
"$test_dir/test-slices"
