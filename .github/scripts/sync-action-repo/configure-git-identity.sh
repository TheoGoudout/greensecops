#!/usr/bin/env bash
# The bot identity every commit this workflow makes is authored as.
set -euo pipefail

git config user.name "greensecops-bot"
git config user.email "bot@greensecops.com"
