#!/bin/zsh
# Baut laser.wasm einmal und packt jedes Kategorie-Plugin (laser-*/) als .zip.
#   ./build.sh            nur bauen + packen
#   ./build.sh install    zusätzlich installieren (SolidCraft vorher beenden, danach neu starten)
set -e
cd "${0:A:h}"
C=/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli
(cd laser-palette-src && cargo build --release --target wasm32-unknown-unknown -q)
wasm-tools component new laser-palette-src/target/wasm32-unknown-unknown/release/laser_palette.wasm -o laser.wasm
for p in laser-*/; do
  p=${p%/}
  [[ -f $p/plugin.json ]] || continue
  cp laser.wasm $p/laser.wasm
  rm -f $p.zip; (cd $p && zip -qr ../$p.zip .)
  if [[ $1 == install ]]; then
    read A R G <<< $($C exec plugin.install "{\"path\":\"$PWD/$p.zip\",\"dry_run\":true}" \
      | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['approval'],d['archive'],json.dumps(d['permissions']['command_groups']).replace(' ',''))")
    $C exec plugin.install "{\"path\":\"$PWD/$p.zip\",\"approval\":\"$A\",\"archive\":\"$R\",\"replace\":true,\"approve\":{\"command_groups\":$G,\"folders\":[]}}" \
      | grep -q '"installed": true' && echo "installiert: $p"
  else
    echo "gepackt: $p"
  fi
done
rm -f laser.wasm
