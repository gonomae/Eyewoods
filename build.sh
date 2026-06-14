#!/bin/sh

mkdir -p build
git describe --dirty > build/version.txt
uv run pyinstaller Eyewoods.spec $1
