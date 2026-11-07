#!/bin/sh
# Copy the Blender export and brand images next to the page (StaticFiles does not follow symlinks).
set -e
cd "$(dirname "$0")/.."
mkdir -p web/static/brand/ads
# meshopt-compress the geometry and animations (lossless for what you see: same nodes, names, clips and textures,
# about half the bytes); the page decodes it with three's MeshoptDecoder
npx --yes @gltf-transform/cli@4.1.1 meshopt blender/quiet-page.glb web/static/quiet-page.glb
cp brand/logo.png brand/menu-board.png web/static/brand/
cp brand/ads/*.png web/static/brand/ads/
ls -la web/static/quiet-page.glb
