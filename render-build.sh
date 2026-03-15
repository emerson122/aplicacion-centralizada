#!/usr/bin/env bash
# Salir si hay un error
set -o errexit

pip install -r requirements.txt

# Descargar ffmpeg estático para Linux si no existe
if [ ! -d "ffmpeg" ]; then
  mkdir -p ffmpeg
  curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-i686-static.tar.xz | tar -xJ -C ffmpeg --strip-components 1
fi
