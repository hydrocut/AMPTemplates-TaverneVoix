#!/bin/bash
# lancer-livekit.sh - pose par le template AMP TeamKit (recree a chaque Update).
#
#   lancer-livekit.sh cle=valeur ...     demarrage du serveur vocal (ligne de commande d'AMP)
#
# AMP passe chaque reglage sous la forme cle=valeur, entre guillemets : un reglage vide reste
# un argument "cle=" et ne decale jamais les autres. La cle d'API et le secret arrivent par les
# variables d'environnement TAVERNE_VOIX_CLE et TAVERNE_VOIX_SECRET (App.EnvironmentVariables,
# champs mot de passe d'AMP) : jamais sur une ligne de commande, jamais dans la console, jamais
# dans un fichier.
#
# Ce script :
#  1. controle chaque reglage et refuse de demarrer avec un message clair si l'un est faux ;
#  2. ecrit livekit.yaml (A CHAQUE demarrage : le modifier a la main ne sert a rien) ;
#  3. lance LiveKit avec les cles dans LIVEKIT_KEYS (variable lue par LiveKit lui-meme) ;
#  4. verifie que LiveKit repond "OK" sur le port de signalisation, puis ecrit la ligne
#     "Voix de la Taverne prete" (regex d'AMP) : elle sort meme quand le journal de LiveKit est
#     en "warn", niveau ou LiveKit n'ecrit pas sa propre ligne de demarrage ;
#  5. a l'arret (SIGTERM d'AMP) : LiveKit attend sinon que tout le monde soit parti ; on lui
#     laisse 5 s puis on lui redemande, ce qui le fait couper tout de suite (arret force).
cd "$(dirname "$0")" || exit 1
ICI="$PWD"
LIVEKIT="$ICI/livekit/livekit-server"
CONFIG="$ICI/livekit.yaml"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

# Seulement les cles connues, chacune une fois : un guillemet colle dans un reglage d'AMP
# (remplacement brut) ne peut pas glisser un argument de plus.
CONNUES=" signal tcp udp ip places vide journal "
declare -A V
for a in "$@"; do
  case "$a" in
    *=*) k="${a%%=*}" ;;
    *) echo "ERREUR : argument inattendu : $a"; exit 1 ;;
  esac
  [[ "$CONNUES" == *" $k "* ]] || { echo "ERREUR : reglage inattendu '$k' (un guillemet dans un reglage d'AMP ?)."; exit 1; }
  [ -z "${V[$k]+x}" ] || { echo "ERREUR : reglage '$k' en double (un guillemet dans un reglage d'AMP ?)."; exit 1; }
  V["$k"]="${a#*=}"
done

refuser() {
  echo "ERREUR : $1"
  echo "Corrige ce reglage dans l'onglet Configuration d'AMP (rubrique Voix de la Taverne), puis relance."
  exit 1
}
borne() {
  [[ "$2" =~ ^[0-9]+$ ]] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] \
    || refuser "$1 : '$2' n'est pas un nombre entre $3 et $4."
}

# --- 1. Cle d'API et secret ------------------------------------------------------------
CLE="${TAVERNE_VOIX_CLE:-}"
SECRET="${TAVERNE_VOIX_SECRET:-}"
unset TAVERNE_VOIX_CLE TAVERNE_VOIX_SECRET
probleme=""
if [ -z "$CLE" ]; then
  probleme="la cle d'API (TAVERNE_VOIX_CLE) est vide"
elif [[ ! "$CLE" =~ ^[A-Za-z][A-Za-z0-9_]{2,63}$ ]]; then
  probleme="la cle d'API doit commencer par une lettre et ne contenir que des lettres, des chiffres ou _ (3 a 64 caracteres)"
elif [ -z "$SECRET" ]; then
  probleme="le secret (TAVERNE_VOIX_SECRET) est vide"
elif [ "${#SECRET}" -lt 32 ]; then
  probleme="le secret est trop court : ${#SECRET} caracteres, il en faut au moins 32"
elif [[ ! "$SECRET" =~ ^[A-Za-z0-9_+/=.-]+$ ]]; then
  probleme="le secret contient un espace, un guillemet ou un caractere special"
elif [[ "$SECRET" == remplacer-par-* ]] || [ "$SECRET" = "$CLE" ]; then
  probleme="le secret est encore celui de l'exemple (ou egal a la cle)"
fi
if [ -n "$probleme" ]; then
  echo "ERREUR : $probleme : la Voix de la Taverne refuse de demarrer."
  echo "  1. Fabrique la cle et le secret (voir LISEZMOI.md du template) :"
  echo "       cle    : echo TK\$(openssl rand -hex 6)"
  echo "       secret : openssl rand -hex 32"
  echo "  2. Colle-les dans AMP : onglet Configuration, rubrique Voix de la Taverne."
  echo "  3. Colle LES MEMES dans l'instance La Taverne (le jeu signe les cles des joueurs avec)."
  echo "  4. Relance l'instance."
  exit 1
fi

# --- 2. Les autres reglages ------------------------------------------------------------
SIGNAL="${V[signal]}"
TCP="${V[tcp]}"
UDP="${V[udp]}"
IP="${V[ip]// /}"
PLACES="${V[places]:-12}"
VIDE="${V[vide]:-60}"
JOURNAL="${V[journal]:-warn}"

borne "port de signalisation" "$SIGNAL" 1024 65535
borne "port TCP de secours" "$TCP" 1024 65535
borne "port UDP de la voix" "$UDP" 1024 65535
[ "$SIGNAL" != "$TCP" ] || refuser "le port de signalisation et le port TCP de secours sont identiques ($TCP) : deux ports TCP differents."
borne "personnes par piece au plus" "$PLACES" 2 50
borne "piece vide fermee apres" "$VIDE" 10 3600
[[ "$JOURNAL" =~ ^(warn|info|error|debug)$ ]] || refuser "niveau du journal '$JOURNAL' : warn, info, error ou debug."

# L'adresse annoncee : dans un conteneur ponte, LiveKit ne voit que 172.17.x.x ; il faut lui donner
# l'adresse IPv4 PUBLIQUE de la machine, sinon les navigateurs n'atteignent jamais la voix.
[ -n "$IP" ] || refuser "l'adresse publique annoncee est vide : mets l'adresse IPv4 publique de la machine."
if [[ "$IP" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]]; then
  for o in "${BASH_REMATCH[@]:1}"; do
    [ "$((10#$o))" -le 255 ] || refuser "adresse publique annoncee '$IP' : chaque nombre va de 0 a 255."
  done
  A=$((10#${BASH_REMATCH[1]})); B=$((10#${BASH_REMATCH[2]}))
  if [ "$A" -eq 10 ] || [ "$A" -eq 127 ] || [ "$A" -eq 0 ] || [ "$A" -ge 224 ] \
    || { [ "$A" -eq 172 ] && [ "$B" -ge 16 ] && [ "$B" -le 31 ]; } \
    || { [ "$A" -eq 192 ] && [ "$B" -eq 168 ]; } || { [ "$A" -eq 169 ] && [ "$B" -eq 254 ]; } \
    || { [ "$A" -eq 100 ] && [ "$B" -ge 64 ] && [ "$B" -le 127 ]; }; then
    refuser "adresse publique annoncee '$IP' : c'est une adresse privee ou locale, injoignable depuis Internet. Mets l'adresse IPv4 publique de la machine."
  fi
  IP="$((10#${BASH_REMATCH[1]})).$((10#${BASH_REMATCH[2]})).$((10#${BASH_REMATCH[3]})).$((10#${BASH_REMATCH[4]}))"
else
  refuser "adresse publique annoncee '$IP' : une adresse IPv4 comme 51.254.47.151 (pas de nom, pas de port)."
fi

# --- 3. LiveKit est-il installe ? --------------------------------------------------------
[ -x "$LIVEKIT" ] || { echo "ERREUR : LiveKit n'est pas installe ($LIVEKIT). Lance Update."; exit 1; }
VERSION=$("$LIVEKIT" --version 2>/dev/null | awk 'NR == 1 { print $NF }')

# --- 4. livekit.yaml (reecrit a chaque demarrage) ---------------------------------------
NOUVEAU="$CONFIG.nouveau"
cat > "$NOUVEAU" <<EOF || { echo "ERREUR : impossible d'ecrire $CONFIG."; exit 1; }
# livekit.yaml - ecrit par lancer-livekit.sh a CHAQUE demarrage, d'apres les reglages d'AMP.
# Le modifier ici ne sert a rien : changer le reglage dans l'onglet Configuration d'AMP.
# Les cles (cle d'API et secret) ne sont PAS ici : elles passent par la variable LIVEKIT_KEYS.
# Pas de TURN, pas d'enregistrement : egress et ingress (les services qui enregistrent ou
# diffusent) ne sont pas installes, et aucune adresse de webhook n'est donnee.
port: $SIGNAL
rtc:
  tcp_port: $TCP
  udp_port: $UDP
  use_external_ip: false
  node_ip: $IP
room:
  auto_create: true
  empty_timeout: $VIDE
  departure_timeout: 20
  max_participants: $PLACES
  enabled_codecs:
    - mime: audio/opus
    - mime: audio/red
turn:
  enabled: false
logging:
  level: $JOURNAL
EOF
mv -f "$NOUVEAU" "$CONFIG" || { echo "ERREUR : impossible d'ecrire $CONFIG."; exit 1; }

# --- 5. LiveKit, sa ligne "prete", son arret ------------------------------------------------
export LIVEKIT_KEYS="$CLE: $SECRET"
unset CLE SECRET
echo "TeamKit : LiveKit ${VERSION:-?}, signalisation port $SIGNAL (via nginx), voix UDP $UDP, secours TCP $TCP, adresse annoncee $IP, $PLACES personnes par piece, journal $JOURNAL"

ARRET=0
ENFANT=""
arreter() {
  ARRET=1
  [ -n "$ENFANT" ] || exit 0
  echo "TeamKit : arret demande : la voix se coupe a toutes les tables."
  kill -TERM "$ENFANT" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$ENFANT" 2>/dev/null || return
    sleep 0.5
  done
  # LiveKit attend que tout le monde soit parti ; un 2e signal le fait couper tout de suite.
  kill -TERM "$ENFANT" 2>/dev/null
}
trap arreter TERM INT

sonde() {
  if command -v curl >/dev/null 2>&1; then
    [ "$(curl -s -m 2 "http://127.0.0.1:$SIGNAL/" 2>/dev/null)" = "OK" ]
  else
    (exec 4<>"/dev/tcp/127.0.0.1/$SIGNAL") 2>/dev/null
  fi
}

"$LIVEKIT" --config "$CONFIG" </dev/null 2>&1 &
ENFANT=$!
unset LIVEKIT_KEYS

PRETE=0
for _ in $(seq 1 120); do
  [ "$ARRET" = 1 ] && break
  kill -0 "$ENFANT" 2>/dev/null || break
  if sonde; then
    PRETE=1
    echo "TeamKit : Voix de la Taverne prete : LiveKit ${VERSION:-?} repond sur le port $SIGNAL."
    break
  fi
  sleep 0.5
done
if [ "$PRETE" = 0 ] && [ "$ARRET" = 0 ] && kill -0 "$ENFANT" 2>/dev/null; then
  echo "TeamKit : ATTENTION : LiveKit tourne mais ne repond pas 'OK' sur le port $SIGNAL apres 60 s. Lis les lignes ci-dessus."
fi

CODE=0
wait "$ENFANT"; CODE=$?
while kill -0 "$ENFANT" 2>/dev/null; do wait "$ENFANT"; CODE=$?; done
[ "$ARRET" = 1 ] && exit 0
if [ "$PRETE" = 0 ]; then
  echo "ERREUR : LiveKit s'est arrete au demarrage (code $CODE). Lis les lignes ci-dessus : port deja pris, reglage refuse..."
else
  echo "ERREUR : LiveKit s'est arrete sans qu'on le lui demande (code $CODE)."
fi
# LiveKit sort avec le code 0 meme quand il refuse sa configuration : un arret non demande
# n'est jamais un succes pour AMP (qui relance alors, Limits.AutoRetryCount).
[ "$CODE" = 0 ] && CODE=1
exit "$CODE"
