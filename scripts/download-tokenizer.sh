#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl --fail --location --silent --show-error \
  https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip \
  -o "$TMP/tokenizer.zip"
unzip -p "$TMP/tokenizer.zip" tokenizer.json > "$ROOT/.deepseek-tokenizer.json"
printf 'Installed tokenizer at %s\n' "$ROOT/.deepseek-tokenizer.json"
