#!/bin/bash
# installer-livekit.sh - pose par le template AMP TeamKit (recree a chaque Update).
#
#   installer-livekit.sh
#
# Installe le serveur vocal LiveKit (programme OFFICIEL publie sur GitHub par LiveKit, licence
# Apache 2.0) dans le dossier de l'instance :
#   livekit/livekit-server   le programme (version et empreinte SHA-256 figees ci-dessous)
#   livekit/LICENSE          sa licence
#   livekit.ancien/          la version d'avant (retour rapide possible)
# Rien d'autre n'est telecharge. Changer de version = changer LIVEKIT_V et LIVEKIT_SHA ici
# (empreinte relevee dans checksums.txt de la release ET recalculee), puis Update.
set -o pipefail
cd "$(dirname "$0")" || exit 1
umask 022
export LANG=C.UTF-8 LC_ALL=C.UTF-8

LIVEKIT_V=1.13.9
# SHA-256 de livekit_1.13.9_linux_amd64.tar.gz, relevee le 14/10/2026 dans
# https://github.com/livekit/livekit/releases/download/v1.13.9/checksums.txt
# (identique au "digest" de l'API GitHub et a l'empreinte recalculee sur le fichier telecharge).
LIVEKIT_SHA=0b7fa208b662d09cfdeae8c06cf4c481aead0556086558b48250501e2e2d6e20
# LIVEKIT_URL_BASE : seulement pour les essais (faux dossier local) ; jamais pose par le template.
URL_BASE="${LIVEKIT_URL_BASE:-https://github.com/livekit/livekit/releases/download}"
F="livekit_${LIVEKIT_V}_linux_amd64.tar.gz"

echec() { echo "ERREUR : $1"; exit 1; }
etape() { echo "TeamKit : $1"; }
nettoyer() { rm -f ".cache/$F"; }
trap nettoyer EXIT

[ "$#" -eq 0 ] || echec "argument inattendu (ce script n'en prend aucun)."
for outil in curl tar sha256sum; do
  command -v "$outil" >/dev/null 2>&1 || echec "l'outil $outil manque dans l'image du conteneur."
done
mkdir -p .cache || echec "impossible de creer le dossier .cache de l'instance."

version_de() { "$1" --version 2>/dev/null | awk 'NR == 1 { print $NF }'; }

if [ -x livekit/livekit-server ] && [ "$(version_de livekit/livekit-server)" = "$LIVEKIT_V" ]; then
  echo "LiveKit $LIVEKIT_V est deja installe : rien a faire."
  exit 0
fi

etape "telechargement de LiveKit $LIVEKIT_V (programme officiel, github.com/livekit/livekit)..."
curl -fsSL --retry 3 --connect-timeout 20 -o ".cache/$F" "$URL_BASE/v$LIVEKIT_V/$F" \
  || echec "telechargement de $F impossible ($URL_BASE). Reseau du conteneur ?"
OBTENUE=$(sha256sum ".cache/$F" | cut -d' ' -f1)
if [ "$OBTENUE" != "$LIVEKIT_SHA" ]; then
  rm -f ".cache/$F"
  echec "empreinte SHA-256 de $F incorrecte (attendue ${LIVEKIT_SHA:0:12}..., obtenue ${OBTENUE:0:12}...) : fichier abime ou modifie, rien n'est installe."
fi
echo "Empreinte SHA-256 verifiee : $LIVEKIT_SHA"

rm -rf livekit.new && mkdir -p livekit.new
tar -xzf ".cache/$F" -C livekit.new --no-same-owner --no-same-permissions livekit-server LICENSE \
  || { rm -rf livekit.new; echec "archive $F illisible (ou sans livekit-server)."; }
rm -f ".cache/$F"
chmod 755 livekit.new/livekit-server
[ "$(version_de livekit.new/livekit-server)" = "$LIVEKIT_V" ] \
  || { rm -rf livekit.new; echec "LiveKit $LIVEKIT_V ne demarre pas dans ce conteneur (livekit-server --version)."; }

AVANT=""
[ -x livekit/livekit-server ] && AVANT=$(version_de livekit/livekit-server)
rm -rf livekit.ancien
[ -d livekit ] && mv livekit livekit.ancien
mv livekit.new livekit || echec "echange des dossiers impossible."
echo "TeamKit : LiveKit $LIVEKIT_V installe${AVANT:+ (a la place de $AVANT, garde dans livekit.ancien/)}."
