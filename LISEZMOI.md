# Voix de la Taverne — le serveur vocal dans AMP

Ce template fait tourner le **vocal de La Taverne** dans une instance AMP à part, « Voix de la Taverne ».
Le programme est **LiveKit 1.13.9** (logiciel libre, licence Apache 2.0).

- **Une pièce vocale par table.** Seuls les joueurs assis y entrent, avec une clé donnée par le jeu.
- **Rien n'est enregistré.** La voix est relayée en direct, en mémoire. Les services qui enregistrent ou diffusent
  (« egress », « ingress ») ne sont pas installés. Pas de relais TURN au début.
- **Rien n'est installé sur la machine** : tout est dans le conteneur de l'instance.

## Comment il s'installe

À chaque **Update**, le script `installer-livekit.sh` télécharge le **programme officiel** de LiveKit sur GitHub
(`livekit_1.13.9_linux_amd64.tar.gz`) et vérifie son **empreinte SHA-256**. Si elle ne correspond pas, rien n'est
installé. L'ancienne version est gardée dans `livekit.ancien/`.

Pour passer à une version plus récente : on change le numéro et l'empreinte dans le script, on pousse le template,
puis **Update** dans AMP.

## Les ports

| Port | Rôle | Ouvert au monde ? |
|---|---|---|
| **7880** TCP | signalisation : les navigateurs passent par `wss://voix.teamkit.fr` (nginx) | **NON** : fermé par le pare-feu |
| **7881** TCP | la voix en secours quand l'UDP est bloqué | oui |
| **7882** UDP | toutes les voix, sur ce seul port | oui |

## Les réglages (onglet Configuration d'AMP, rubrique « Voix de la Taverne »)

| Réglage | À quoi il sert | Par défaut |
|---|---|---|
| **Clé d'API** | le nom de la clé (mot de passe, obligatoire) | vide : refus de démarrer |
| **Secret** | signe et vérifie les clés des joueurs (mot de passe, 32 caractères au moins) | vide : refus de démarrer |
| **Adresse publique annoncée** | l'adresse IPv4 publique de la machine, donnée aux navigateurs | `51.254.47.151` |
| **Personnes par pièce au plus** | une pièce = une table | 12 |
| **Pièce vide fermée après** | une pièce où personne n'entre est fermée | 60 secondes |
| **Niveau du journal** | `warn` = le moins de lignes, et donc le moins d'adresses gardées | warn |

**La clé et le secret se mettent aux DEUX endroits** : ici, et dans l'instance La Taverne (le jeu s'en sert pour
donner les clés des joueurs et pour faire sortir un joueur d'une pièce).

Pour les fabriquer (dans Git Bash, ou sur le dédié) :

```
echo TK$(openssl rand -hex 6)
openssl rand -hex 32
```

La première ligne donne la **clé d'API** (par exemple `TK3f9a1c0b7e2d`), la deuxième le **secret** (64 caractères).

Dans PowerShell, si Git Bash n'est pas là :

```
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | ForEach-Object { $_.ToString('x2') }) -join ''
```

## Le fichier livekit.yaml

Il est **écrit à chaque démarrage** par `lancer-livekit.sh`, d'après les réglages d'AMP. Le modifier à la main ne
sert à rien. Il ne contient **jamais** la clé ni le secret : ils passent par la variable `LIVEKIT_KEYS`.

## Ce que dit la console

```
TeamKit : LiveKit 1.13.9, signalisation port 7880 (via nginx), voix UDP 7882, secours TCP 7881, adresse annoncee 51.254.47.151, 12 personnes par piece, journal warn
TeamKit : Voix de la Taverne prete : LiveKit 1.13.9 repond sur le port 7880.
```

La 2e ligne n'arrive qu'une fois que LiveKit répond vraiment « OK ». C'est elle qui passe l'instance en « prête » dans
AMP. En journal `warn`, LiveKit n'écrit pas sa propre ligne de démarrage : le script l'écrit à sa place.

Sur le dédié, une ligne `UDP receive buffer is too small for a production set-up` peut apparaître : c'est un conseil
pour des milliers de personnes, sans gêne à notre échelle.

Si un réglage est faux, l'instance refuse de démarrer et dit quoi faire, par exemple :

```
ERREUR : le secret (TAVERNE_VOIX_SECRET) est vide : la Voix de la Taverne refuse de demarrer.
```

## À l'arrêt

La voix se coupe à toutes les tables. Les joueurs se reconnectent tout seuls quand l'instance repart.

## Avant de pousser

```
python verifier.py
```

Il doit répondre « Tout est bon. ». Avec `LIVEKIT_EXE=<chemin du programme livekit-server 1.13.9>`, il lance aussi le
vrai LiveKit avec le fichier écrit par le script, **en local seulement** (aucun port ouvert).
