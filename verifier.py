# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de La Taverne et de Mumble).

    python verifier.py
    LIVEKIT_EXE=<chemin de livekit-server(.exe) 1.13.9> python verifier.py      (+ essai réel, étape 10)
    LIVEKIT_ARCHIVE=<chemin de livekit_1.13.9_linux_amd64.tar.gz> python verifier.py (+ empreinte, étape 8)

1. tous les JSON se parsent ;
2. le .kvp : fichiers inclus, bloc Console.* / Limits.* complet, image Debian, conteneur obligatoire, arrêt par
   SIGTERM, RegexMatch avec un motif NON vide, même dépôt que le manifest, identifiants neufs ;
3. les ports : 7880 TCP (signalisation, derrière nginx), 7881 TCP (secours), 7882 UDP (voix), hors 8080-8125 ;
4. les réglages : rubriques avec le bon nombre de « : », chacun passé une fois (ligne de commande ou environnement),
   clé et secret en mot de passe, vides par défaut, exclus de l'import, jamais sur la ligne de commande ;
   clés passées = clés lues par le lanceur ; chaque réglage exposé se retrouve dans le livekit.yaml livré ;
5. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest ;
6. les scripts : LF, ASCII, aucun {{, `bash -n` ; LiveKit 1.13.9 figé avec son empreinte ;
7. le VRAI lanceur sous bash (LiveKit et curl remplacés par des bouchons) : livekit.yaml écrit (sans clé, sans TURN,
   sans enregistrement), LIVEKIT_KEYS donné à LiveKit, variables TAVERNE_VOIX_* retirées, secret jamais affiché,
   ligne « prête » après la sonde, arrêt (2e SIGTERM après 5 s), refus clairs ;
8. le VRAI installateur sous bash : déjà installé, empreinte fausse refusée sans rien installer ;
9. la regex « prête » d'AMP sur les vraies lignes de LiveKit 1.13.9 (essai du 14/10/2026) et du lanceur ;
10. (si LIVEKIT_EXE) le vrai LiveKit lancé avec le livekit.yaml écrit par le lanceur, en boucle locale seulement :
    il accepte le fichier (mode strict), répond OK, refuse sans jeton, accepte un jeton signé avec la clé ;
11. aucun secret dans le dépôt.
"""
import base64
import glob
import hashlib
import hmac
import http.server
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'tavernevoix'
LANCEUR = 'scripts/lancer-livekit.sh'
INSTALLEUR = 'scripts/installer-livekit.sh'
VERSION = '1.13.9'
SHA_OFFICIELLE = '0b7fa208b662d09cfdeae8c06cf4c481aead0556086558b48250501e2e2d6e20'  # checksums.txt + digest GitHub, 14/10/2026
soucis = []


def lire(nom, binaire=False):
    with open(os.path.join(ICI, nom), 'rb') as f:
        brut = f.read()
    return brut if binaire else brut.decode('utf-8')


def ok(quoi, detail):
    print('ok   %-24s %s' % (quoi, detail))


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...)
    return re.compile(motif.replace('(?<', '(?P<'))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        ok(nom, 'JSON valide')
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']
manifest = data['manifest.json']
lanceur = lire(LANCEUR)
installeur = lire(INSTALLEUR)

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest', 'Meta.ConfigRoot'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex',
             'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex',
             'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex',
             'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex',
             'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart',
             'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
ATTENDU_KVP = {
    'Meta.SpecificDockerImage': 'cubecoders/ampbase:debian',
    'Meta.ContainerPolicy': 'Required',
    'Meta.DockerRequired': 'True',
    'Meta.ExtraContainerPackages': '[]',
    'Meta.EndpointURIFormat': 'https://voix.teamkit.fr',
    'App.ExecutableLinux': '/bin/bash',
    'App.ExitMethod': 'SIGTERM',
    'App.HasReadableConsole': 'True',
    'App.ApplicationReadyMode': 'RegexMatch',
    'App.RootDir': './voix/',
    'App.BaseDirectory': './voix/',
    'App.PrimaryApplicationPortRef': 'SignalPort',
    'App.EnvironmentVariables': '{"TAVERNE_VOIX_CLE":"{{CleApi}}","TAVERNE_VOIX_SECRET":"{{SecretApi}}"}',
    'Limits.SleepMode': 'False',
}
for cle, val in ATTENDU_KVP.items():
    if cles.get(cle) != val:
        soucis.append('%s devrait valoir %s (vaut %r)' % (cle, val, cles.get(cle)))
if not cles.get('Console.AppReadyRegex'):
    soucis.append('ApplicationReadyMode=RegexMatch exige un Console.AppReadyRegex NON vide (sinon l\'instance n\'est jamais prête)')
if not 1 <= int(cles.get('Limits.AutoRetryCount', '0')) <= 3:
    soucis.append('Limits.AutoRetryCount : 1 à 3 relances après un plantage')
if int(cles.get('App.ExitTimeout', '0')) < 15:
    soucis.append('App.ExitTimeout doit laisser au lanceur ses 5 s + l\'arrêt de LiveKit (>= 15)')
if cles.get('Meta.URL') != manifest['url'] or manifest['origin'] != manifest['url'] + '.git':
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')
if manifest.get('authors') != ['Hydrocut', 'TeamKit'] or not manifest.get('prefix', '').startswith('TeamKit'):
    soucis.append('manifest : auteurs Hydrocut + TeamKit, prefix TeamKit…')
autres = [p for p in glob.glob(os.path.join(ICI, '..', 'AMPTemplates-*', '*'))
          if os.path.abspath(os.path.dirname(p)) != ICI and p.endswith(('.kvp', 'manifest.json'))]
deja = ''.join(io.open(p, encoding='utf-8', errors='replace').read() for p in autres if os.path.isfile(p))
for quoi, val in (('Meta.AppConfigId', cles.get('Meta.AppConfigId', '')), ('id du manifest', manifest['id'])):
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', val):
        soucis.append('%s : UUID v4 attendu (%r)' % (quoi, val))
    elif val in deja:
        soucis.append('%s déjà utilisé par un autre template TeamKit' % quoi)
if cles.get('Meta.AppConfigId') == manifest['id']:
    soucis.append('AppConfigId et id du manifest doivent différer')
if not [s for s in soucis if 'kvp' in s or 'Meta' in s or 'App.' in s or 'Console' in s or 'Limits' in s]:
    ok('kvp', 'Debian, conteneur obligatoire, SIGTERM, regex « prête » non vide, %d autres templates lus' % len(autres))

# ── 3. ports ─────────────────────────────────────────────────────────────────
ATTENDU_PORTS = {'SignalPort': ('TCP', 7880), 'RtcTcpPort': ('TCP', 7881), 'RtcUdpPort': ('UDP', 7882)}
vus = {p['Ref']: (p['Protocol'], p['Port']) for p in ports}
if vus != ATTENDU_PORTS or len(ports) != 3:
    soucis.append('ports : %r attendus, %r trouvés' % (ATTENDU_PORTS, vus))
elif any(8080 <= p['Port'] <= 8125 for p in ports):
    soucis.append('un port tombe dans la plage des panneaux d\'AMP (8080-8125)')
elif 'NE PAS ouvrir' not in next(p['Description'] for p in ports if p['Ref'] == 'SignalPort'):
    soucis.append('le port de signalisation doit dire qu\'il reste fermé au monde')
else:
    ok('ports', '7880/TCP signalisation (fermé au monde), 7881/TCP secours, 7882/UDP voix')

# ── 4. réglages ──────────────────────────────────────────────────────────────
for c in config:
    for cle, n in (('Category', 1), ('Subcategory', 2)):
        if c.get(cle) and c[cle].count(':') != n:
            soucis.append('%s : %s %r doit avoir exactement %d « : »' % (c['FieldName'], cle, c[cle], n))
    if c.get('IncludeInCommandLine') is not False:
        soucis.append('%s : IncludeInCommandLine doit être false' % c['FieldName'])
par_nom = {c['FieldName']: c for c in config}
if len(par_nom) != len(config) or len({c['ParamFieldName'] for c in config}) != len(config):
    soucis.append('réglages en double')
ligne = cles['App.CommandLineArgs']
env_kvp = cles['App.EnvironmentVariables']
for c in config:
    nb = ligne.count('{{%s}}' % c['FieldName']) + env_kvp.count('{{%s}}' % c['FieldName'])
    if nb != 1:
        soucis.append('{{%s}} doit être passé exactement une fois (ligne de commande ou environnement) : %d' % (c['FieldName'], nb))
SECRETS = ('CleApi', 'SecretApi')
for s in SECRETS:
    c = par_nom.get(s, {})
    if c.get('InputType') != 'password' or not c.get('ExcludeFromImport') or c.get('DefaultValue') != '':
        soucis.append('%s : mot de passe, exclu de l\'import, vide par défaut' % s)
    if '{{%s}}' % s in ligne:
        soucis.append('%s ne doit jamais être sur la ligne de commande' % s)
passes = re.findall(r'"([a-z]+)=\{\{([$A-Za-z0-9_]+)\}\}"', ligne)
lues = set(re.findall(r'\$\{V\[(\w+)\]', lanceur))
connues = set(re.search(r'^CONNUES=" ([a-z ]+) "$', lanceur, re.M).group(1).split())
if {k for k, _ in passes} != lues or lues != connues:
    soucis.append('clés passées %s / lues %s / connues %s par le lanceur : différentes'
                  % (sorted({k for k, _ in passes}), sorted(lues), sorted(connues)))
for _, champ in passes:
    if champ.startswith('$') and champ[1:] not in ATTENDU_PORTS:
        soucis.append('{{%s}} : aucun port ne porte ce Ref' % champ)
if data[NOM + 'metaconfig.json'] != []:
    soucis.append('metaconfig : aucun fichier rendu par AMP (livekit.yaml est écrit par le lanceur)')
if not [s for s in soucis if 'réglage' in s or '{{' in s or 'clé' in s or 'Cle' in s or 'Secret' in s]:
    ok('réglages', '%d réglages + 3 ports, lanceur d\'accord, clé et secret protégés' % len(config))

# ── 5. fichiers de l'Update ───────────────────────────────────────────────────
brut = 'https://raw.githubusercontent.com/' + manifest['url'].split('github.com/')[1] + '/main/'
for u in updates:
    if u['UpdateSource'] == 'FetchURL':
        url = u['UpdateSourceData']
        if not url.startswith(brut + 'scripts/') or not os.path.isfile(os.path.join(ICI, url[len(brut):])):
            soucis.append('Update : %s ne pointe pas sur un fichier de scripts/ de ce dépôt' % url)
        if u['UpdateSourceArgs'] != url.rsplit('/', 1)[1] or u['UpdateSourceTarget'] != '{{$FullBaseDir}}':
            soucis.append('Update : %s mal rangé' % url)
if updates[-1]['UpdateSource'] != 'Executable' or updates[-1]['UpdateSourceData'] != '/bin/bash' \
        or 'installer-livekit.sh' not in updates[-1]['UpdateSourceArgs'] or VERSION not in updates[-1]['UpdateStageName']:
    soucis.append('dernière étape de l\'Update : /bin/bash installer-livekit.sh (LiveKit %s)' % VERSION)
if 'lancer-livekit.sh' not in ligne:
    soucis.append('la ligne de commande doit lancer lancer-livekit.sh')
ok('Update', '%d étapes, scripts de ce dépôt' % len(updates))

# ── 6. scripts ───────────────────────────────────────────────────────────────
for s in (LANCEUR, INSTALLEUR):
    b = lire(s, True)
    if b'\r' in b:
        soucis.append('%s : fins de ligne CRLF (bash les refuse)' % s)
    try:
        b.decode('ascii')
    except UnicodeDecodeError:
        soucis.append('%s : caractères non ASCII' % s)
    if b'{{' in b:
        soucis.append('%s : « {{ » serait remplacé par AMP' % s)
if not re.search(r'^LIVEKIT_V=%s$' % re.escape(VERSION), installeur, re.M):
    soucis.append('LiveKit %s doit être figé dans l\'installateur (LIVEKIT_V=)' % VERSION)
if not re.search(r'^LIVEKIT_SHA=%s$' % SHA_OFFICIELLE, installeur, re.M):
    soucis.append('empreinte SHA-256 de LiveKit absente ou différente de celle publiée')


def trouver_bash():
    for c in (r'C:\Program Files\Git\bin\bash.exe', r'C:\Program Files\Git\usr\bin\bash.exe', '/bin/bash'):
        if os.path.isfile(c):
            return c
    c = shutil.which('bash')
    if c and 'system32' not in c.lower():   # le bash de WSL ne verrait pas les chemins Windows
        return c
    return None


bash = trouver_bash()
if bash:
    for s in (LANCEUR, INSTALLEUR):
        r = subprocess.run([bash, '-n', os.path.join(ICI, s)], capture_output=True, text=True)
        if r.returncode:
            soucis.append('bash -n %s : %s' % (s, r.stderr.strip()))
    ok('scripts', 'LF, ASCII, bash -n, LiveKit %s figé (SHA-256 %s…)' % (VERSION, SHA_OFFICIELLE[:12]))


def unix(p):
    return p.replace('\\', '/')


def rendre(modele, valeurs):
    """Remplacement brut des {{Réglage}} comme AMP, puis découpe en arguments entre guillemets."""
    for k, v in valeurs.items():
        modele = modele.replace('{{%s}}' % k, v)
    return re.findall(r'"([^"]*)"', modele)


def ecrire(chemin, texte):
    with open(chemin, 'w', encoding='utf-8', newline='\n') as f:
        f.write(texte)


CLE_ESSAI = 'TK' + os.urandom(6).hex()
SECRET_ESSAI = os.urandom(32).hex()
DEFAUTS = {c['FieldName']: c.get('DefaultValue', '') for c in config}
yaml_livre = None

# ── 7. le vrai lanceur ───────────────────────────────────────────────────────
if not bash:
    print('---  lanceur / installateur    bash introuvable : étapes 7 et 8 sautées (à faire avant de pousser)')
else:
    tmp = tempfile.mkdtemp(prefix='voix-lanceur-')
    try:
        inst = os.path.join(tmp, 'voix')
        os.makedirs(os.path.join(inst, 'livekit'))
        shutil.copy(os.path.join(ICI, LANCEUR), inst)
        bouchon = os.path.join(inst, 'livekit', 'livekit-server')
        ecrire(bouchon, '#!/bin/bash\n'
               'if [ "$1" = "--version" ]; then echo "livekit-server version 1.13.9"; exit 0; fi\n'
               'D="$(dirname "$0")/.."\n'
               '{ printf "ARGS"; printf " [%s]" "$@"; echo; echo "KEYS=[$LIVEKIT_KEYS]";'
               ' echo "TAVERNE_VOIX=$(env | grep -c "^TAVERNE_VOIX_")"; } > "$D/bouchon.txt"\n'
               'cp "$2" "$D/bouchon.yaml"\n'
               'if [ "$BOUCHON" = plante ]; then echo "faux refus de configuration"; exit 0; fi\n'
               'n=0\n'
               'trap \'n=$((n+1)); echo "BOUCHON SIGTERM $n"; [ $n -ge 2 ] && exit 0\' TERM\n'
               'touch "$D/pret"\n'
               'while :; do sleep 0.1; done\n')
        faux = os.path.join(tmp, 'faux')
        os.makedirs(faux)
        ecrire(os.path.join(faux, 'curl'), '#!/bin/bash\n'
               'echo "$@" >> "$FAUX_CURL_TRACE"\n'
               '[ -f "$FAUX_CURL_PRET" ] && printf OK\nexit 0\n')
        pilote = os.path.join(tmp, 'pilote.sh')
        ecrire(pilote, '#!/bin/bash\n'
               'SORTIE="$1"; shift\n'
               'export PATH="$(cygpath -u "$FAUX_BIN" 2>/dev/null || echo "$FAUX_BIN"):$PATH"\n'
               '"$BASH" "$@" > "$SORTIE" 2>&1 &\nL=$!\n'
               'for i in $(seq 1 150); do grep -q "prete" "$SORTIE" && break; kill -0 $L 2>/dev/null || break; sleep 0.1; done\n'
               'kill -0 $L 2>/dev/null && kill -TERM $L\n'
               'wait $L; echo "CODE=$?" >> "$SORTIE"\n')

        def lancer(reglages=None, cle=CLE_ESSAI, secret=SECRET_ESSAI, mode='normal', ports=(7880, 7881, 7882), brut=None):
            for f in ('bouchon.txt', 'bouchon.yaml', 'pret', 'livekit.yaml', 'sortie.txt', 'curl.txt'):
                if os.path.exists(os.path.join(inst, f)):
                    os.remove(os.path.join(inst, f))
            valeurs = dict(DEFAUTS)
            valeurs.update(reglages or {})
            valeurs['$FullBaseDir'] = unix(inst) + '/'
            valeurs['$SignalPort'], valeurs['$RtcTcpPort'], valeurs['$RtcUdpPort'] = (str(p) for p in ports)
            args = brut if brut is not None else rendre(ligne, valeurs)
            env = dict(os.environ)
            env.update({'TAVERNE_VOIX_CLE': cle, 'TAVERNE_VOIX_SECRET': secret, 'BOUCHON': mode,
                        'FAUX_CURL_PRET': unix(os.path.join(inst, 'pret')),
                        'FAUX_CURL_TRACE': unix(os.path.join(inst, 'curl.txt')), 'FAUX_BIN': unix(faux),
                        'PATH': faux + os.pathsep + env.get('PATH', '')})
            sortie = os.path.join(inst, 'sortie.txt')
            p = subprocess.run([bash, unix(pilote), unix(sortie)] + args, env=env, capture_output=True, timeout=60)
            texte = open(sortie, encoding='utf-8', errors='replace').read() if os.path.exists(sortie) else ''
            code = re.search(r'CODE=(\d+)', texte)
            def lu(f):
                q = os.path.join(inst, f)
                return open(q, encoding='utf-8').read() if os.path.exists(q) else None
            return int(code.group(1)) if code else -1, texte, lu('bouchon.txt'), lu('bouchon.yaml'), lu('curl.txt')

        n7 = 0
        # a) réglages par défaut, comme AMP les rend
        code, texte, trace, yml, curl = lancer()
        ATTENDU_YAML = ['port: 7880', 'rtc:', '  tcp_port: 7881', '  udp_port: 7882', '  use_external_ip: false',
                        '  node_ip: 51.254.47.151', 'room:', '  auto_create: true', '  empty_timeout: 60',
                        '  departure_timeout: 20', '  max_participants: 12', '  enabled_codecs:', '    - mime: audio/opus',
                        '    - mime: audio/red', 'turn:', '  enabled: false', 'logging:', '  level: warn']
        lignes = [l for l in (yml or '').splitlines() if l.strip() and not l.lstrip().startswith('#')]
        if lignes != ATTENDU_YAML:
            soucis.append('livekit.yaml écrit (défauts) : %r' % lignes)
        else:
            yaml_livre = yml
        for interdit in ('keys', 'key_file', 'webhook', 'egress', 'ingress', 'redis', 'development', 'port_range'):
            if re.search(r'^\s*%s\s*:' % interdit, yml or '', re.M):
                soucis.append('livekit.yaml ne doit pas contenir « %s: »' % interdit)
        if SECRET_ESSAI in (yml or '') or SECRET_ESSAI in texte:
            soucis.append('le secret apparaît dans livekit.yaml ou dans la console')
        if not trace or 'KEYS=[%s: %s]' % (CLE_ESSAI, SECRET_ESSAI) not in trace:
            soucis.append('LiveKit ne reçoit pas LIVEKIT_KEYS = « clé: secret »')
        if not trace or 'TAVERNE_VOIX=0' not in trace:
            soucis.append('TAVERNE_VOIX_CLE / TAVERNE_VOIX_SECRET doivent être retirées avant de lancer LiveKit')
        if not trace or not re.search(r'^ARGS \[--config\] \[[^\]]*/livekit\.yaml\]$', trace, re.M):
            soucis.append('LiveKit doit être lancé avec --config livekit.yaml et rien d\'autre : %r' % trace)
        pret = [l for l in texte.splitlines() if py(cles['Console.AppReadyRegex']).search(l)]
        if len(pret) != 1 or 'LiveKit 1.13.9 repond sur le port 7880.' not in pret[0]:
            soucis.append('ligne « prête » du lanceur absente ou non reconnue par AppReadyRegex : %r' % texte)
        if not curl or 'http://127.0.0.1:7880/' not in curl:
            soucis.append('la sonde doit interroger http://127.0.0.1:7880/ (dans le conteneur) : %r' % curl)
        if texte.count('BOUCHON SIGTERM') != 2 or 'CODE=0' not in texte or 'arret demande' not in texte:
            soucis.append('arrêt : SIGTERM transmis, 2e SIGTERM après 5 s, sortie 0 : %r' % texte)
        n7 += 1

        # b) réglages changés, adresse avec des zéros
        code, texte, trace, yml, _ = lancer({'MaxPlaces': '6', 'PieceVide': '120', 'NiveauJournal': 'info',
                                             'AdresseAnnoncee': ' 051.254.047.151 '}, ports=(7890, 7891, 7892))
        for attendu in ('port: 7890', '  tcp_port: 7891', '  udp_port: 7892', '  node_ip: 51.254.47.151',
                        '  max_participants: 6', '  empty_timeout: 120', '  level: info'):
            if attendu not in (yml or '').splitlines():
                soucis.append('réglage changé non écrit dans livekit.yaml : %r' % attendu)
        n7 += 1

        # c) LiveKit qui refuse sa configuration (il sort alors avec le code 0) : pas de « prête », code 1 pour AMP
        code, texte, trace, yml, _ = lancer(mode='plante')
        if code != 1 or 'prete' in texte or 's\'est arrete au demarrage' not in texte:
            soucis.append('LiveKit planté au démarrage : code 1 et message attendus : %r' % texte)
        n7 += 1

        # d) refus clairs, LiveKit jamais lancé
        REFUS = [
            ({}, '', SECRET_ESSAI, 'cle d\'API (TAVERNE_VOIX_CLE) est vide'),
            ({}, 'TK 12', SECRET_ESSAI, 'commencer par une lettre'),
            ({}, '1abc', SECRET_ESSAI, 'commencer par une lettre'),
            ({}, CLE_ESSAI, '', 'secret (TAVERNE_VOIX_SECRET) est vide'),
            ({}, CLE_ESSAI, 'court', 'trop court'),
            ({}, CLE_ESSAI, 'a' * 31, 'trop court'),
            ({}, CLE_ESSAI, 'a' * 40 + '"b', 'caractere special'),
            ({}, CLE_ESSAI, 'a' * 40 + ' b', 'caractere special'),
            ({}, CLE_ESSAI, 'remplacer-par-un-secret-de-64-caracteres-xxxxxx', 'exemple'),
            ({'AdresseAnnoncee': ''}, CLE_ESSAI, SECRET_ESSAI, 'est vide'),
            ({'AdresseAnnoncee': '192.168.1.20'}, CLE_ESSAI, SECRET_ESSAI, 'adresse privee'),
            ({'AdresseAnnoncee': '172.17.0.5'}, CLE_ESSAI, SECRET_ESSAI, 'adresse privee'),
            ({'AdresseAnnoncee': '127.0.0.1'}, CLE_ESSAI, SECRET_ESSAI, 'adresse privee'),
            ({'AdresseAnnoncee': '10.0.0.1'}, CLE_ESSAI, SECRET_ESSAI, 'adresse privee'),
            ({'AdresseAnnoncee': '51.254.47'}, CLE_ESSAI, SECRET_ESSAI, 'une adresse IPv4'),
            ({'AdresseAnnoncee': 'voix.teamkit.fr'}, CLE_ESSAI, SECRET_ESSAI, 'une adresse IPv4'),
            ({'AdresseAnnoncee': '51.254.47.300'}, CLE_ESSAI, SECRET_ESSAI, 'de 0 a 255'),
            ({'MaxPlaces': '1'}, CLE_ESSAI, SECRET_ESSAI, 'entre 2 et 50'),
            ({'MaxPlaces': 'douze'}, CLE_ESSAI, SECRET_ESSAI, 'entre 2 et 50'),
            ({'PieceVide': '5'}, CLE_ESSAI, SECRET_ESSAI, 'entre 10 et 3600'),
            ({'NiveauJournal': 'bavard'}, CLE_ESSAI, SECRET_ESSAI, 'warn, info, error ou debug'),
            ({'NiveauJournal': 'warn" "signal=1'}, CLE_ESSAI, SECRET_ESSAI, 'en double'),
        ]
        for reglages, cle, secret, attendu in REFUS:
            code, texte, trace, yml, _ = lancer(reglages, cle=cle, secret=secret)
            if code != 1 or attendu not in texte or trace is not None or (secret and len(secret) > 8 and secret in texte):
                soucis.append('refus attendu (%s) pour %r / clé %r : code %d, %r' % (attendu, reglages, cle, code, texte[-300:]))
            n7 += 1
        # ports en double, argument en trop ou en double
        valeurs = dict(DEFAUTS, **{'$FullBaseDir': unix(inst) + '/', '$SignalPort': '7880', '$RtcTcpPort': '7880', '$RtcUdpPort': '7882'})
        for args, attendu in ((rendre(ligne, valeurs), 'identiques'),
                              (rendre(ligne.replace('"journal=', '"signal=7880" "journal='), dict(valeurs, **{'$RtcTcpPort': '7881'})), 'en double'),
                              (rendre(ligne + ' "turn=oui"', dict(valeurs, **{'$RtcTcpPort': '7881'})), 'inattendu')):
            code, texte, trace, *_ = lancer(brut=args)
            if code != 1 or attendu not in texte or trace is not None:
                soucis.append('refus attendu (%s) : code %d, %r' % (attendu, code, texte[-300:]))
            n7 += 1
        # LiveKit absent
        os.rename(bouchon, bouchon + '.cache')
        code, texte, trace, *_ = lancer()
        os.rename(bouchon + '.cache', bouchon)
        if code != 1 or 'Lance Update' not in texte:
            soucis.append('LiveKit absent : refus « Lance Update » attendu : %r' % texte)
        n7 += 1
        if not [s for s in soucis if 'livekit.yaml' in s or 'refus' in s or 'LIVEKIT' in s or 'prête' in s or 'arrêt' in s]:
            ok('lanceur (bash)', '%d cas : livekit.yaml, clés par l\'environnement, « prête », arrêt, refus' % n7)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ── 8. le vrai installateur ──────────────────────────────────────────────────
archive = os.environ.get('LIVEKIT_ARCHIVE')
if archive and os.path.isfile(archive):
    with open(archive, 'rb') as f:
        if hashlib.sha256(f.read()).hexdigest() != SHA_OFFICIELLE:
            soucis.append('%s : empreinte différente de celle figée' % archive)
        else:
            ok('archive officielle', 'SHA-256 recalculée = celle figée dans l\'installateur')
if bash:
    tmp = tempfile.mkdtemp(prefix='voix-installateur-')
    serveur = None
    try:
        inst = os.path.join(tmp, 'voix')
        os.makedirs(inst)
        shutil.copy(os.path.join(ICI, INSTALLEUR), inst)
        depot = os.path.join(tmp, 'depot', 'v' + VERSION)
        os.makedirs(depot)
        with open(os.path.join(depot, 'livekit_%s_linux_amd64.tar.gz' % VERSION), 'wb') as f:
            f.write(b'pas la vraie archive')

        class Silence(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=os.path.join(tmp, 'depot'), **k)

            def log_message(self, *a):
                pass
        serveur = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Silence)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        base = 'http://127.0.0.1:%d' % serveur.server_address[1]

        def installer(*args, url=base):
            env = dict(os.environ, LIVEKIT_URL_BASE=url)
            p = subprocess.run([bash, unix(os.path.join(inst, 'installer-livekit.sh'))] + list(args),
                               env=env, capture_output=True, timeout=120)
            return p.returncode, (p.stdout + p.stderr).decode('utf-8', 'replace')

        m8 = 0
        code, texte = installer()
        if code != 1 or 'empreinte SHA-256' not in texte or os.path.exists(os.path.join(inst, 'livekit')) \
                or glob.glob(os.path.join(inst, '.cache', '*')):
            soucis.append('installateur : une archive à la mauvaise empreinte doit être refusée sans rien laisser : %r' % texte)
        m8 += 1
        code, texte = installer('version=1.0.0')
        if code != 1 or 'argument inattendu' not in texte:
            soucis.append('installateur : argument inattendu à refuser : %r' % texte)
        m8 += 1
        os.makedirs(os.path.join(inst, 'livekit'))
        ecrire(os.path.join(inst, 'livekit', 'livekit-server'), '#!/bin/bash\necho "livekit-server version %s"\n' % VERSION)
        code, texte = installer(url='http://127.0.0.1:9')  # aucun téléchargement : le réseau ne doit pas servir
        if code != 0 or 'deja installe' not in texte:
            soucis.append('installateur : version déjà en place = rien à faire : %r' % texte)
        m8 += 1
        if not [s for s in soucis if 'installateur' in s]:
            ok('installateur (bash)', '%d cas : empreinte fausse refusée, argument refusé, déjà installé' % m8)
    finally:
        if serveur:
            serveur.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

# ── 9. regex « prête » sur de vraies lignes ──────────────────────────────────
# Lignes réelles de livekit-server 1.13.9 (essai local du 14/10/2026, journal « info », format console de zap).
ESSAIS = [
    '2026-10-14T09:19:06.189+0200\tINFO\tlivekit\tservice/server.go:309\tstarting LiveKit server\t{"portHttp": 7880, "nodeID": "ND_kwCCW62GBrLu", "nodeIP": "51.254.47.151", "version": "1.13.9", "bindAddresses": ["127.0.0.1"], "rtc.portUDP": {"Start":7882,"End":0}}',
    '2026-10-14T09:19:06.189+0200\tINFO\tlivekit\tservice/server.go:309\tstarting LiveKit server\t{"portHttp": 7880, "nodeID": "ND_kwCCW62GBrLu", "nodeIP": "51.254.47.151", "version": "1.13.9", "rtc.portTCP": 7881, "rtc.portUDP": {"Start":7882,"End":0}}',
    'TeamKit : Voix de la Taverne prete : LiveKit 1.13.9 repond sur le port 7880.',
]
REFUS_REGEX = [
    '2026-10-14T09:19:05.850+0200\tINFO\tlivekit\trouting/interfaces.go:181\tusing single-node routing',
    '2026-10-14T09:19:05.852+0200\tINFO\tlivekit\trtcconfig/webrtc_config.go:112\tusing explicit node IP for NAT1To1Ips\t{"ip": {"V4":"51.254.47.151","V6":""}, "advertiseInternalIP": false}',
    '2026-10-14T09:19:06.189+0200\tINFO\tlivekit\tservice/server.go:311\tWindows detected, capacity management is unavailable',
    '2026-10-14T09:19:07.318+0200\tWARN\tlivekit\tservice/utils.go:85\terror handling request\t{"status": 401, "method": "GET", "path": "/rtc/validate", "error": "no permissions to access the room"}',
    '2026-10-14T09:19:26.540+0200\tERROR\tlivekit\tconfig/config.go:850\tsecret is too short, should be at least 32 characters for security\t{"apiKey": "cle"}',
    'one of key-file or keys must be provided',
    'TeamKit : LiveKit 1.13.9, signalisation port 7880 (via nginx), voix UDP 7882, secours TCP 7881, adresse annoncee 51.254.47.151, 12 personnes par piece, journal warn',
    'TeamKit : ATTENTION : LiveKit tourne mais ne repond pas \'OK\' sur le port 7880 apres 60 s. Lis les lignes ci-dessus.',
    'TeamKit : arret demande : la voix se coupe a toutes les tables.',
    'Un joueur dit : TeamKit : Voix de la Taverne prete : LiveKit 1.13.9 repond sur le port 7880.',
]
motif = py(cles['Console.AppReadyRegex'])
for l in ESSAIS:
    if not motif.search(l):
        soucis.append('AppReadyRegex devrait reconnaître %r' % l)
for l in REFUS_REGEX:
    if motif.search(l):
        soucis.append('AppReadyRegex ne devrait pas reconnaître %r' % l)
if not [s for s in soucis if 'AppReadyRegex' in s]:
    ok('regex de console', '%d vraies lignes reconnues, %d refusées' % (len(ESSAIS), len(REFUS_REGEX)))

# ── 10. essai réel (facultatif) ──────────────────────────────────────────────
exe = os.environ.get('LIVEKIT_EXE')
if not exe:
    print('---  essai réel                LIVEKIT_EXE non donné : étape 10 sautée')
elif not os.path.isfile(exe) or yaml_livre is None:
    soucis.append('essai réel : %s introuvable, ou livekit.yaml non produit à l\'étape 7' % exe)
else:
    tmp = tempfile.mkdtemp(prefix='voix-essai-')
    proc = None
    try:
        # Le livekit.yaml du lanceur, en boucle locale SEULEMENT (aucun port ouvert, aucune alerte du pare-feu
        # de Windows) : écoute sur 127.0.0.1, secours TCP coupé (il écouterait sur toutes les adresses),
        # UDP limité à 127.0.0.1, journal « info » pour lire la ligne de démarrage de LiveKit.
        essai = yaml_livre.replace('port: 7880\n', 'port: 7880\nbind_addresses:\n  - 127.0.0.1\n', 1)
        essai = essai.replace('  tcp_port: 7881\n', '  tcp_port: 0\n')
        essai = essai.replace('rtc:\n', 'rtc:\n  enable_loopback_candidate: true\n  ips:\n    includes:\n      - 127.0.0.1/32\n', 1)
        essai = essai.replace('  level: warn', '  level: info')
        chemin = os.path.join(tmp, 'livekit.yaml')
        ecrire(chemin, essai)
        journal = open(os.path.join(tmp, 'sortie.txt'), 'w+', encoding='utf-8')
        env = dict(os.environ, LIVEKIT_KEYS='%s: %s' % (CLE_ESSAI, SECRET_ESSAI))
        proc = subprocess.Popen([exe, '--config', chemin], stdout=journal, stderr=subprocess.STDOUT, env=env, cwd=tmp)

        def get(url):
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    return r.status, r.read().decode('utf-8', 'replace')
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode('utf-8', 'replace')
            except Exception as e:
                return 0, str(e)
        reponse = (0, '')
        for _ in range(60):
            reponse = get('http://127.0.0.1:7880/')
            if reponse == (200, 'OK') or proc.poll() is not None:
                break
            time.sleep(0.25)

        def b64(o):
            return base64.urlsafe_b64encode(json.dumps(o, separators=(',', ':')).encode()).rstrip(b'=').decode()
        maintenant = int(time.time())
        corps = b64({'alg': 'HS256', 'typ': 'JWT'}) + '.' + b64({
            'iss': CLE_ESSAI, 'sub': 'essai', 'nbf': maintenant - 10, 'exp': maintenant + 300,
            'video': {'roomJoin': True, 'room': 'table-ESSAI', 'canPublish': True, 'canSubscribe': True,
                      'canPublishData': False, 'canPublishSources': ['microphone']}})
        jeton = corps + '.' + base64.urlsafe_b64encode(hmac.new(SECRET_ESSAI.encode(), corps.encode(), hashlib.sha256).digest()).rstrip(b'=').decode()
        sans = get('http://127.0.0.1:7880/rtc/validate')
        avec = get('http://127.0.0.1:7880/rtc/validate?access_token=' + jeton)
        faux = get('http://127.0.0.1:7880/rtc/validate?access_token=' + jeton[:-4] + 'AAAA')
        proc.terminate()
        proc.wait(10)
        journal.seek(0)
        sortie = journal.read()
        journal.close()
        demarrage = [l for l in sortie.splitlines() if 'starting LiveKit server' in l]
        if reponse != (200, 'OK'):
            soucis.append('essai réel : LiveKit ne répond pas OK sur 7880 (%r) : %s' % (reponse, sortie[-800:]))
        elif len(demarrage) != 1 or not motif.search(demarrage[0]) or '"version": "%s"' % VERSION not in demarrage[0]:
            soucis.append('essai réel : ligne de démarrage absente ou non reconnue : %r' % demarrage)
        elif 'using explicit node IP for NAT1To1Ips' not in sortie or '51.254.47.151' not in sortie or '"rtc.portUDP": {"Start":7882' not in demarrage[0]:
            soucis.append('essai réel : adresse annoncée ou port UDP non pris en compte : %s' % sortie[-800:])
        elif sans[0] != 401 or avec[0] != 200 or faux[0] != 401:
            soucis.append('essai réel : /rtc/validate sans jeton %r, avec jeton %r, jeton abîmé %r' % (sans, avec, faux))
        elif SECRET_ESSAI in sortie:
            soucis.append('essai réel : le secret apparaît dans le journal de LiveKit')
        else:
            ok('essai réel', 'LiveKit %s : livekit.yaml accepté (mode strict), OK sur 7880, jeton signé accepté, sans jeton 401' % VERSION)
            print('     ' + demarrage[0].replace('\t', '  '))
    finally:
        if proc and proc.poll() is None:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

# ── 11. aucun secret dans le dépôt ───────────────────────────────────────────
for chemin in glob.glob(os.path.join(ICI, '**', '*'), recursive=True):
    if os.path.isfile(chemin) and '.git' + os.sep not in chemin and not chemin.endswith('verifier.py'):
        texte = open(chemin, encoding='utf-8', errors='replace').read()
        for m in re.finditer(r'\b[0-9a-f]{40,}\b', texte):
            if m.group(0) != SHA_OFFICIELLE:
                soucis.append('%s : longue suite hexadécimale (un secret ?) : %s…' % (os.path.relpath(chemin, ICI), m.group(0)[:8]))
        if re.search(r'LIVEKIT_KEYS\s*=\s*["\']?[A-Za-z]\w+:\s*\S{16,}', texte):
            soucis.append('%s : LIVEKIT_KEYS avec une valeur' % os.path.relpath(chemin, ICI))
if not [s for s in soucis if 'secret ?' in s or 'avec une valeur' in s]:
    ok('secrets', 'aucun dans le dépôt')

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
