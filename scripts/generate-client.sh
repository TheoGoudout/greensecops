#! /usr/bin/env bash
set -ex

# openapi-ts leaves trailing whitespace and no EOF newline; fix them so
# pre-commit hooks (trim-trailing-whitespace, end-of-file-fixer) pass.
fix_generated_files() {
    for f in "$1"/src/client/*.ts "$1"/src/client/core/*.ts; do
        [ -f "$f" ] || continue
        sed -i 's/[[:space:]]*$//' "$f"
        [ -n "$(tail -c 1 "$f")" ] && printf '\n' >> "$f"
    done
}

cd backend
uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
cd ..

cp openapi.json frontend/
bun run --filter frontend generate-client
fix_generated_files frontend

mv openapi.json action/
bun run --filter action generate-client
fix_generated_files action
