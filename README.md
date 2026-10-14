# AMPTemplates-TaverneVoix — voice server of La Taverne (LiveKit) for AMP

**AMP Generic Module** template for the voice chat of **La Taverne**, TeamKit's 3D card and board game lounge.
It runs **LiveKit server 1.13.9** (open source, Apache 2.0): one voice room per game table, voice relayed live,
**never recorded**. Written for TeamKit, a free French game host, in October 2026.

> Notice en français : [LISEZMOI.md](LISEZMOI.md).

## What it does

| | |
|---|---|
| Server | the **official** `livekit_1.13.9_linux_amd64.tar.gz` from GitHub releases, SHA-256 pinned in `scripts/installer-livekit.sh` (same value as the release's `checksums.txt` and GitHub's asset digest) |
| Image | `cubecoders/ampbase:debian`, **container required**, bridged network (uses `curl`, `tar`, `sha256sum` of the image) |
| Ports | **7880/TCP** signalling (WebSocket) — **behind nginx only** (`wss://voix.teamkit.fr`), closed to the world by the host firewall · **7881/TCP** ICE/TCP fallback · **7882/UDP** all voice traffic on one port (UDP mux, no 50000-60000 range) |
| Keys | API key and secret are AMP **password fields**, passed as environment variables, turned into `LIVEKIT_KEYS` by the start script; never on a command line, in the console or in a file |
| Config | `livekit.yaml` is **written by the start script at every start** from AMP's settings (editing it by hand is useless) |
| Not installed | no TURN, no Egress/Ingress (recording/streaming), no webhook, no Redis (single node) |
| Ready | `Console.AppReadyRegex` matches LiveKit's own `starting LiveKit server` line (log level `info`) **or** the start script's line `TeamKit : Voix de la Taverne prete : …`, printed after `GET http://127.0.0.1:7880/` answers `OK` — needed because at the default `warn` level LiveKit prints no start line |
| Stop | AMP's SIGTERM is passed to LiveKit, which would wait for every participant to leave; after 5 s the script sends a second SIGTERM (LiveKit's forced stop) |

Generated `livekit.yaml` (defaults):

```yaml
port: 7880
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: false
  node_ip: 51.254.47.151        # setting « Adresse publique annoncée »: the host's public IPv4
room:
  auto_create: true
  empty_timeout: 60             # « Pièce vide fermée après »
  departure_timeout: 20
  max_participants: 12          # « Personnes par pièce au plus »
  enabled_codecs:
    - mime: audio/opus
    - mime: audio/red           # Opus redundancy used by livekit-client; no video codec
turn:
  enabled: false
logging:
  level: warn                   # « Niveau du journal »
```

In a bridged container LiveKit only sees `172.17.x.x`: with `use_external_ip: false` and an explicit `node_ip`, it
replaces its host candidate with the public address (`using explicit node IP for NAT1To1Ips`). The published port
numbers must be the same outside and inside the container (AMP's default).

## Settings exposed in AMP (French UI)

| Setting | Goes to | Default |
|---|---|---|
| Clé d'API (password, required) | `TAVERNE_VOIX_CLE` → `LIVEKIT_KEYS` | empty → refuses to start |
| Secret (password, required, ≥ 32 chars) | `TAVERNE_VOIX_SECRET` → `LIVEKIT_KEYS` | empty → refuses to start |
| Adresse publique annoncée | `rtc.node_ip` (private/loopback addresses refused) | `51.254.47.151` |
| Personnes par pièce au plus | `room.max_participants` (2-50) | 12 |
| Pièce vide fermée après | `room.empty_timeout` (10-3600 s) | 60 |
| Niveau du journal | `logging.level` (warn, info, error, debug) | warn |
| Ports (AMP's port settings) | `port`, `rtc.tcp_port`, `rtc.udp_port` | 7880, 7881, 7882 |

The same key and secret go into the La Taverne instance (`TAVERNE_VOIX_CLE`, `TAVERNE_VOIX_SECRET`): the game signs
short-lived room tokens with them and calls `RoomService` through `https://voix.teamkit.fr` to remove a player.

## Before pushing

`python verifier.py` must print `Tout est bon.` It checks the JSON, the `.kvp`, the ports, every setting, then runs
the **real** start script under bash (LiveKit and curl replaced by stubs, 29 cases: generated `livekit.yaml`, keys
through the environment, ready line, stop, clear refusals) and the real installer (wrong SHA-256 refused, already
installed). With `LIVEKIT_EXE=<path to livekit-server 1.13.9>` it also starts the **real** LiveKit with the generated
file on loopback only: strict config accepted, `OK` on 7880, a token signed with the key accepted, no token → 401.

## Install in AMP

1. ADS → Configuration → Instance Deployment → **Configuration Repositories**: add `hydrocut/AMPTemplates-TaverneVoix:main`, save, **Fetch latest** (ADS clones without credentials: this repository must be public).
2. Create an instance « Voix de la Taverne - serveur vocal LiveKit (TeamKit) » (container), fill in the key and the secret.
3. **Update**, then **Start**. The console shows `Voix de la Taverne prete` when ready.

A « Fetch latest » does **not** update an existing instance's `App.*`/`Console.*` keys nor its settings form: after a
template change, recreate the instance or copy the keys by hand.
