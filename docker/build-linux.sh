#!/usr/bin/env bash
# Builds the Linux portable version in Docker (x86_64, Ubuntu 22.04 → runs on Ubuntu 22.04+, Debian 12+).
# Usage (from the project folder):  bash docker/build-linux.sh
set -euo pipefail
export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
cd "$(dirname "$0")/.."
docker run --rm --platform linux/amd64 -v "$PWD":/src:ro -v "$PWD/dist":/out ubuntu:22.04 bash -c '
  set -e
  apt-get update -qq
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -qq python3 python3-venv python3-pip binutils libegl1 libgl1 libfontconfig1 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 \
      libglib2.0-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
      libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xfixes0 >/dev/null
  mkdir /w && cd /w
  tar -C /src --exclude=./dist --exclude=./build --exclude=./.git -cf - . | tar -xf -
  python3 -m venv /venv && . /venv/bin/activate
  pip install -q -U pip && pip install -q -r requirements.txt
  QT_QPA_PLATFORM=offscreen python -m pytest -q
  QT_QPA_PLATFORM=offscreen python build_app.py
  cp -r dist/SpecRec-Linux-portable* /out/
  chown -R '"$(id -u):$(id -g)"' /out/SpecRec-Linux-portable*
'
