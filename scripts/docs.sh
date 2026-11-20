#!/usr/bin/env bash
#
# Build and preview the VIRA documentation using a project-local virtualenv.
# This avoids picking up a system MkDocs that does not have Material installed.
#
#   ./scripts/docs.sh serve [port]   # live preview, default 127.0.0.1:8001
#   ./scripts/docs.sh build          # strict HTML build into site/
#   ./scripts/docs.sh pdf            # both PDF manuals into site-pdf/
#   ./scripts/docs.sh clean          # remove build output
#
# Override the venv location with DOCS_VENV, or the interpreter used to export
# the OpenAPI schema with PYTHON_FOR_EXPORT.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV="${DOCS_VENV:-$ROOT/.venv}"
MKDOCS="$VENV/bin/mkdocs"

if [[ ! -x "$MKDOCS" ]]; then
  echo "Creating documentation venv at $VENV ..."
  "${PYTHON:-python3}" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$ROOT/requirements-docs.txt"
fi

generate_openapi() {
  # The API page needs docs/reference/openapi.json. Generation imports the app,
  # so it needs the runtime dependencies. Best-effort: a missing schema does not
  # block the rest of the site.
  if [[ ! -f "$ROOT/docs/reference/openapi.json" ]]; then
    echo "Generating docs/reference/openapi.json ..."
    "${PYTHON_FOR_EXPORT:-python3}" "$ROOT/scripts/export_openapi.py" >/dev/null 2>&1 \
      || echo "warning: could not export OpenAPI (install requirements.txt); the API page will be empty."
  fi
}

case "${1:-serve}" in
  serve)
    generate_openapi
    exec "$MKDOCS" serve --strict -a "${2:-127.0.0.1:8001}"
    ;;
  build)
    generate_openapi
    exec "$MKDOCS" build --strict
    ;;
  pdf)
    generate_openapi
    ENABLE_PDF_EXPORT=1 "$MKDOCS" build -f "$ROOT/mkdocs.pdf-user.yml"
    ENABLE_PDF_EXPORT=1 "$MKDOCS" build -f "$ROOT/mkdocs.pdf-dev.yml"
    echo
    echo "User manual:      $ROOT/site-pdf/user/pdf/vira-user-manual.pdf"
    echo "Developer manual: $ROOT/site-pdf/dev/pdf/vira-developer-manual.pdf"
    ;;
  clean)
    rm -rf "$ROOT/site" "$ROOT/site-pdf"
    echo "Removed site/ and site-pdf/"
    ;;
  *)
    echo "Usage: $0 {serve [port]|build|pdf|clean}" >&2
    exit 1
    ;;
esac
