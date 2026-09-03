#!/usr/bin/env bash
# Put the two .env files in place from their committed examples.
#
# Every job that boots the stack needs this and nothing more; the three
# <workflow>/prepare-env-files.sh scripts call it and then append the one or
# two values their own job needs on top. It used to be the first two lines of
# each of them, plus an inline `cp … && cp …` in test-docker-compose.yml — four
# copies of the same pair of paths, which is exactly one copy too many for the
# day frontend/.env.example moves.
set -euo pipefail

cp .env.example .env
cp frontend/.env.example frontend/.env
