#! /usr/bin/env bash

set -e
set -x

cd backend
uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
cd ..
mv openapi.json frontend/
bun run --filter frontend generate-client

# openapi-ts leaves trailing whitespace and no EOF newline; fix them so
# pre-commit hooks (trim-trailing-whitespace, end-of-file-fixer) pass.
for f in frontend/src/client/sdk.gen.ts frontend/src/client/schemas.gen.ts frontend/src/client/types.gen.ts; do
    sed -i 's/[[:space:]]*$//' "$f"
    [ -n "$(tail -c 1 "$f")" ] && printf '\n' >> "$f"
done

bun run lint
