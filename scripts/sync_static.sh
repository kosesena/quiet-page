#!/bin/sh
# Copy the Blender export and brand images next to the page (StaticFiles does not follow symlinks).
set -e
cd "$(dirname "$0")/.."
mkdir -p web/static/brand/ads
cp blender/quiet-page.glb web/static/quiet-page.glb
cp brand/logo.png brand/menu-board.png web/static/brand/
cp brand/ads/*.png web/static/brand/ads/
ls -la web/static web/static/brand
