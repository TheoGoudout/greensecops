#!/usr/bin/env bash
# Install the Session Manager plugin onto a runner.
#
# Ansible reaches the instances over Session Manager; the plugin is the local
# half of that transport and is not preinstalled on the runner.
set -euo pipefail

curl -fsSL -o /tmp/session-manager-plugin.deb \
  "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb"
sudo dpkg -i /tmp/session-manager-plugin.deb
session-manager-plugin --version
