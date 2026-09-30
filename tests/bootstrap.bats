#!/usr/bin/env bats

setup() {
  export TEST_ROOT="$BATS_TEST_TMPDIR/bootstrap"
  mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/source/terminal-kit/lib/terminalkit"
  export PATH="$TEST_ROOT/bin:$PATH"
  export REPO_ROOT="$BATS_TEST_DIRNAME/.."
  cat > "$TEST_ROOT/bin/curl" <<'SH'
#!/bin/bash
set -eu
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ]; then dest=$2; shift 2; else url=$1; shift; fi
done
if [ "${DOWNLOAD_FAIL:-0}" = 1 ]; then exit 22; fi
case "$url" in *SHA256SUMS) cp "$TEST_ROOT/SHA256SUMS" "$dest" ;; *) cp "$TEST_ROOT/artifact.tar.gz" "$dest" ;; esac
SH
  chmod +x "$TEST_ROOT/bin/curl"
  printf '#!/bin/bash\nprintf installed\\n\n' > "$TEST_ROOT/source/terminal-kit/install.sh"
  printf '# valid marker\n' > "$TEST_ROOT/source/terminal-kit/lib/terminalkit/cli.py"
  tar -czf "$TEST_ROOT/artifact.tar.gz" -C "$TEST_ROOT/source" terminal-kit
  hash=$(hash_file "$TEST_ROOT/artifact.tar.gz")
  printf '%s  terminal-kit-v0.1.0.tar.gz\n' "$hash" > "$TEST_ROOT/SHA256SUMS"
}

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

@test "complete verified bootstrap executes the full installer" {
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl
  [ "$status" -eq 0 ]
  [[ "$output" == *installed* ]]
}

@test "HTTP failure stops without execution" {
  export DOWNLOAD_FAIL=1
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl
  [ "$status" -ne 0 ]
  [[ "$output" != *installed* ]]
}

@test "bad checksum stops without execution" {
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl --sha256 0000000000000000000000000000000000000000000000000000000000000000
  [ "$status" -ne 0 ]
  [[ "$output" == *mismatch* ]]
}

@test "HTML archives stop without execution" {
  printf '<html>error</html>' > "$TEST_ROOT/artifact.tar.gz"
  hash=$(hash_file "$TEST_ROOT/artifact.tar.gz")
  printf '%s  terminal-kit-v0.1.0.tar.gz\n' "$hash" > "$TEST_ROOT/SHA256SUMS"
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl
  [ "$status" -ne 0 ]
  [[ "$output" != *installed* ]]
}

@test "truncated archives stop even with a matching checksum" {
  head -c 40 "$TEST_ROOT/artifact.tar.gz" > "$TEST_ROOT/truncated"
  mv "$TEST_ROOT/truncated" "$TEST_ROOT/artifact.tar.gz"
  hash=$(hash_file "$TEST_ROOT/artifact.tar.gz")
  printf '%s  terminal-kit-v0.1.0.tar.gz\n' "$hash" > "$TEST_ROOT/SHA256SUMS"
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl
  [ "$status" -ne 0 ]
  [[ "$output" != *installed* ]]
}

@test "archive symlinks are refused even with a matching checksum" {
  ln -s /tmp "$TEST_ROOT/source/terminal-kit/unsafe"
  tar -czf "$TEST_ROOT/artifact.tar.gz" -C "$TEST_ROOT/source" terminal-kit
  hash=$(hash_file "$TEST_ROOT/artifact.tar.gz")
  printf '%s  terminal-kit-v0.1.0.tar.gz\n' "$hash" > "$TEST_ROOT/SHA256SUMS"
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl
  [ "$status" -ne 0 ]
  [[ "$output" == *links* ]]
}

@test "a multi-megabyte archive is not truncated by pipe reads" {
  dd if=/dev/zero of="$TEST_ROOT/source/terminal-kit/padding" bs=1048576 count=3
  tar -czf "$TEST_ROOT/artifact.tar.gz" -C "$TEST_ROOT/source" terminal-kit
  hash=$(hash_file "$TEST_ROOT/artifact.tar.gz")
  printf '%s  terminal-kit-v0.1.0.tar.gz\n' "$hash" > "$TEST_ROOT/SHA256SUMS"
  run bash "$REPO_ROOT/bootstrap.sh" --transport curl
  [ "$status" -eq 0 ]
  [[ "$output" == *installed* ]]
}

@test "unsafe repository and ref values never reach transport" {
  run bash "$REPO_ROOT/bootstrap.sh" --repo '../bad' --transport curl
  [ "$status" -eq 2 ]
  run bash "$REPO_ROOT/bootstrap.sh" --ref '../bad' --transport curl
  [ "$status" -eq 2 ]
}
