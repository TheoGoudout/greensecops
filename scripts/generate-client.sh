#! /usr/bin/env bash
set -ex

cd backend
uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
cd ..

cp openapi.json frontend/
bun run --filter frontend generate-client

# openapi-ts leaves trailing whitespace and no EOF newline; fix them so
# pre-commit hooks (trim-trailing-whitespace, end-of-file-fixer) pass.
for f in frontend/src/client/*.ts frontend/src/client/core/*.ts; do
    sed -i 's/[[:space:]]*$//' "$f"
    [ -n "$(tail -c 1 "$f")" ] && printf '\n' >> "$f"
done

mv openapi.json action/
bun run --filter action generate-client

# openapi-ts leaves trailing whitespace and no EOF newline; fix them so
# pre-commit hooks (trim-trailing-whitespace, end-of-file-fixer) pass.
for f in action/src/client/*.ts action/src/client/core/*.ts; do
    [ -f "$f" ] || continue
    sed -i 's/[[:space:]]*$//' "$f"
    [ -n "$(tail -c 1 "$f")" ] && printf '\n' >> "$f"
done
