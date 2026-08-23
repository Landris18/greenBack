# GreenSI

Outil Green IT orienté action. Quatre fonctions :

1. **Détecter** automatiquement les conteneurs Docker actifs, groupés par projet Compose, sans aucune configuration.
2. **Mesurer** en temps réel, à la seconde, et estimer énergie et empreinte carbone.
3. **Analyser** consommations et fichiers de configuration, détecter les dépassements de seuils.
4. **Recommander** des modifications concrètes du `Dockerfile` / `docker-compose.yml` sous forme de diff, puis vérifier le résultat.

> La puissance est **mesurée** au niveau de la machine quand un capteur matériel est accessible, et
> **calculée** par un modèle documenté sinon. La part attribuée à un conteneur est dans tous les cas
> une répartition, jamais une mesure électrique directe de ce conteneur.

La plateforme tient en **deux dépôts** :

| Dépôt | Contenu |
| --- | --- |
| [`greenBack`](https://github.com/Landris18/greenBack) | API, collecteur, **orchestration de toute la pile** |
| [`greenFront`](https://github.com/Landris18/greenFront) | interface React |

## Démarrage

Les deux dépôts doivent être clonés **côte à côte**, le `docker-compose.yml` de `greenBack`
construisant l'image du front depuis `../greenFront`.

```bash
git clone https://github.com/Landris18/greenBack.git
git clone https://github.com/Landris18/greenFront.git
cd greenBack
./scripts/initialiser.sh
```

Le script crée le `.env` à partir de `.env.example`, y place une clé secrète aléatoire, l'UID et le
GID de l'utilisateur courant ainsi que son dossier personnel comme racine des projets observés, puis
démarre la pile. Sans argument supplémentaire, tout est prêt.

| Service | Adresse | Rôle |
| --- | --- | --- |
| `front` | <http://localhost:3000> | Interface React, 5 écrans |
| `api` | <http://localhost:8000> — `/docs` | API REST FastAPI |
| `collector` | interne | Streaming Docker 1 s + métriques hôte + lecture des fichiers de config |
| `docker-socket-proxy` | interne uniquement | Accès Docker **en lecture seule** |
| `postgres` | localhost:5433 | Base de données |

Compte initial : `admin@greensi.fr` / valeur de `SEED_ADMIN_PASSWORD` dans le `.env`.

## Architecture

```text
                    docker-socket-proxy         lecture seule, POST=0
                    (reseau interne, non publie)   pas d'ecriture possible
                            ^
                            | tcp://docker-socket-proxy:2375
   front (nginx)  ->  api (uvicorn)        collector
        :3000            :8000          /host/proc:ro
                            \             /
                              postgres:16
```

`api` et `collector` partagent la même image, avec des cibles Dockerfile différentes. **Seul le
collector a un accès Docker et au système de fichiers**, et l'accès Docker passe uniquement par le
proxy en lecture seule. L'API, exposée sur le réseau, ne peut ni exécuter une commande Docker ni lire
un fichier de l'hôte.

Le collector tourne avec l'UID de l'utilisateur propriétaire des projets (`HOST_UID`), pas en root :
il ne peut lire que ce que cet utilisateur peut déjà lire.

### Collecte en streaming

`GET /containers/{id}/stats?stream=false` bloque **2 secondes fixes** — le polling à la seconde est
impossible par cette voie. Le collector ouvre donc une connexion `stream=true` permanente par
conteneur : Docker pousse **exactement une trame par seconde**.

```text
superviseur (10 s)      -> liste les conteneurs, cree les projets, ouvre/ferme les flux
N flux permanents (1 s) -> une trame par seconde et par conteneur, mise en cache memoire
tick d'agregation (1 s) -> puissance hote, attribution, ecriture dans live_sample
                        -> tous les 10 ticks : container_metric_sample + energy_sample
purge (60 s)            -> supprime les mesures live au-dela de la retention
```

Les trames des différents conteneurs ne sont pas synchronisées : l'agrégation utilise la dernière
trame connue de chacun, donc **jusqu'à 1 seconde d'ancienneté**, et ignore toute trame de plus de
3 secondes. C'est une limite à déclarer dans le mémoire.

Aucune énergie n'est perdue entre les deux cadences : l'énergie de chaque seconde est accumulée puis
écrite telle quelle lors de la persistance. Vérification :

```sql
SELECT sum(energy_wh) FROM live_sample WHERE collected_at > :precedent AND collected_at <= :persiste;
SELECT sum(energy_wh) FROM energy_sample WHERE collected_at = :persiste AND NOT is_overhead;
```

Ces deux sommes sont égales à la douzième décimale.

Vérification du cloisonnement :

```bash
docker compose exec collector curl -s -o /dev/null -w '%{http_code}\n' http://docker-socket-proxy:2375/containers/json      # 200
docker compose exec collector curl -s -o /dev/null -w '%{http_code}\n' -X POST http://docker-socket-proxy:2375/containers/create  # 403
curl -s http://localhost:2375/containers/json                                                                               # injoignable
```

## Modèle énergétique

Trois niveaux distincts, jamais confondus dans l'interface :

1. **Mesure observée** — CPU, mémoire, réseau, I/O par conteneur (Docker Engine API) ; CPU, mémoire,
   I/O, réseau de l'hôte (psutil).
2. **Puissance de la machine** — mesurée sur un capteur matériel quand il en existe un, calculée par
   le modèle sinon. La source retenue est enregistrée sur **chaque** échantillon (voir plus bas).
3. **Attribution** — seule la puissance **dynamique** est imputée aux conteneurs, au prorata d'une
   part de ressources pondérée et rapportée à l'**usage réel de l'hôte** :

```text
P_dynamique = max(0, P_hôte − P_idle)
w_i = 0,70·(cpu_i/cpu_hôte) + 0,20·(mem_i/mem_hôte) + 0,06·(io_i/io_hôte) + 0,04·(net_i/net_hôte)
P_i = P_dynamique × w_i
Overhead = P_hôte − Σ P_i
```

Les dénominateurs sont l'usage mesuré de l'hôte, pas sa capacité : si on normalisait par la somme des
conteneurs supervisés, la charge des processus non supervisés leur serait injustement redistribuée.
Ici **`Overhead` absorbe la puissance à vide et le non-supervisé** — ce qui est la réalité.

Invariant vérifiable sur données réelles :

```sql
SELECT e.collected_at,
       sum(e.power_watts)                    AS somme_attribuee,
       max(h.power_watts)                    AS puissance_hote,
       sum(e.power_watts) - max(h.power_watts) AS ecart
FROM energy_sample e
JOIN host_metric_sample h ON h.host_id = e.host_id AND h.collected_at = e.collected_at
GROUP BY e.collected_at ORDER BY e.collected_at DESC LIMIT 5;
```

Puis `kWh = W × durée / 3 600 000` et `gCO₂e = kWh × facteur d'émission`.

### Sources de puissance

Le collector interroge à chaque seconde la première source disponible dans cet ordre :

| Ordre | Source | Portée | Disponible sur |
| --- | --- | --- | --- |
| 1 | **BMC / Redfish** | châssis entier, alimentations comprises | serveur dédié avec contrôleur d'administration |
| 2 | **Batterie** | machine entière, pendant la décharge | portable |
| 3 | **hwmon** | capteur d'alimentation ou de VRM | carte mère qui l'expose |
| 4 | **RAPL** | processeur et mémoire | machine physique Intel ou AMD |
| 5 | **Modèle** | aucune, calcul | partout, y compris en machine virtuelle |

Quatre points de méthode :

- La majoration `non_cpu_overhead_ratio` ne s'applique **qu'à RAPL**. Les autres sources couvrent
  déjà la machine entière ; la leur appliquer gonflerait la valeur.
- RAPL ne somme que les zones de premier niveau : `intel-rapl:N` contient déjà ses sous-zones `core`
  et `uncore`. Le domaine `dram` est en revanche distinct et s'ajoute. Si `psys` existe, il couvre
  toute la plateforme et s'utilise seul.
- La batterie n'est lue que si son `status` vaut `Discharging`, sinon `power_now` retombe à zéro et
  serait pris pour 0 W. Repli sur `current_now × voltage_now` quand `power_now` n'existe pas.
- Les capteurs hwmon de batterie sont écartés pour ne pas compter deux fois la même mesure.

Le collector journalise au démarrage ce qu'il a trouvé, et l'inventaire est exposé par
`GET /api/hosts/{id}` dans `measurement_sources`.

### Le cas des machines virtuelles

`powercap` n'est pas exposé aux invités de virtualisation, et une VM n'a ni BMC, ni batterie, ni
capteur d'alimentation. **Aucune mesure matérielle n'y est possible.** Le collector détecte le
drapeau `hypervisor` de `/proc/cpuinfo`, bascule sur le modèle et l'écrit dans ses journaux ; la
puce d'interface affiche alors `estimé`.

C'est un résultat en soi : la capacité de mesure décroît à mesure que l'on monte dans les couches
d'abstraction, ce qui limite le Green IT en environnement mutualisé.

### Activer RAPL

`/sys/devices/virtual/powercap/intel-rapl:*/energy_uj` n'est lisible que par root, en raison de la
mitigation de l'attaque Platypus. Le collector tourne en utilisateur non privilégié et le **reste** :

```bash
sudo ./scripts/activer-mesure-rapl.sh
```

Le script crée un groupe système, ouvre les compteurs en lecture à ce groupe, installe une règle udev
pour que cela survive au redémarrage, et affiche le `RAPL_GID` à reporter dans `.env`. Sans lui, rien
ne casse : RAPL reste illisible et la chaîne descend d'un cran.

## Analyse des fichiers de configuration

Le label Docker `com.docker.compose.project.config_files` donne le chemin absolu du compose sur
l'hôte. Quand un projet est marqué comme suivi, le collector le lit, en extrait les Dockerfile
référencés par `build.context` / `build.dockerfile`, et stocke un instantané en base.

Un **garde anti-traversée** refuse tout chemin hors de `PROJECTS_ROOT`, y compris après résolution
des liens symboliques. Ce contrôle est couvert par des tests dédiés.

Les règles d'analyse **croisent la configuration et les métriques observées** — c'est ce croisement
qui distingue l'outil d'un simple linter :

| Règle | Détection | Diff propose |
| --- | --- | --- |
| `HEAVY_BASE_IMAGE` | `FROM python:3.12` sans variante légère | `python:3.12-slim` |
| `NO_MULTISTAGE_BUILD` | un seul `FROM` + outils de compilation | guidance, pas de diff automatique |
| `APT_CACHE_NOT_CLEANED` | `apt-get install` sans nettoyage | ligne corrigée |
| `RUNS_AS_ROOT` | aucune instruction `USER` | utilisateur non privilégié |
| `COMPOSE_NO_LIMITS` | service sans `cpus` / `mem_limit` | valeurs issues du p95 observé × 1,5 |
| `COMPOSE_LIMIT_TOO_HIGH` | limite très supérieure au p95 observé | valeur ajustée |
| `UNUSED_SERVICE` | service dont le conteneur est inactif | suppression du bloc |

**GreenSI n'écrit jamais sur vos fichiers.** Il propose un diff, vous l'appliquez, vous relancez, et
la vue Temps réel mesure l'écart. C'est cohérent avec le `POST=0` du proxy Docker.

## Honnêteté des gains

Sur l'ensemble des règles, **deux seulement produisent un chiffre en kWh défendable** :

| Règle | Gain kWh |
| --- | --- |
| `IDLE_CONTAINER`, `UNUSED_SERVICE` | **oui** — la consommation dynamique réellement attribuée, extrapolée sur 30 jours |
| `CPU_OVERPROVISIONED`, `MEMORY_OVERPROVISIONED`, `NO_LIMITS_SET`, `COMPOSE_NO_LIMITS`, `COMPOSE_LIMIT_TOO_HIGH` | non — gain de densité, pas d'énergie |
| `HEAVY_BASE_IMAGE`, `NO_MULTISTAGE_BUILD`, `APT_CACHE_NOT_CLEANED`, `OVERSIZED_IMAGE` | non — gain de stockage et de transfert |
| `CPU_HIGH`, `MEMORY_HIGH`, `RESTART_LOOP` | non — risque de saturation et fiabilité |
| `RUNS_AS_ROOT` | non — surface d'attaque |

Les seuils de saturation `CPU_HIGH` et `MEMORY_HIGH` sont relatifs à **la limite du conteneur**, pas
à la capacité de l'hôte : un conteneur limité à 0,5 cœur peut être étranglé à 84 % de sa limite tout
en n'occupant que 3,5 % de la machine.

Abaisser une limite CPU sur un conteneur qui ne l'atteignait jamais ne fait économiser aucun watt.
Le KPI « Économies potentielles » ne somme donc que les gains calculés ; les autres affichent
explicitement « non quantifiable en kWh ».

## Reproductibilité

Chaque `energy_sample` référence la version de `green_config` qui a servi à le calculer. Modifier le
facteur d'émission ou une pondération crée une **nouvelle version** et ne réécrit jamais le passé.

## Expérimentation avant/après

```bash
docker compose -f demo/docker-compose.before.yml up -d --build
docker compose -f demo/docker-compose.after.yml  up -d --build
```

| | Avant | Après |
| --- | --- | --- |
| Image applicative | `python:3.12` + build-essential, numpy, pandas | multi-stage → `python:3.12-slim` |
| Taille (API Docker) | 450 Mo | 41 Mo |
| Limites CPU/mémoire | aucune | `cpus`, `mem_limit` définis |
| Services | api, db, cache, admin, load | api, db, load |

Les deux stacks tournent **en parallèle** et sont détectées automatiquement. Ouvrir la vue
**Temps réel**, sélectionner les deux projets, et regarder les deux courbes d'énergie cumulée
s'écarter seconde après seconde. La comparaison porte sur la même fenêtre temporelle et le même état
de la machine — le seul moyen d'éliminer le biais « la machine était plus chargée hier ».

Note : avec le magasin d'images containerd, `docker images` affiche une taille (1,88 Go) différente
de celle exposée par l'API Docker (450 Mo). La plateforme utilise la valeur de l'API des deux côtés,
donc la comparaison reste cohérente.

## Tests

```bash
docker compose run --rm --entrypoint sh api -c "pytest"
cd ../greenFront && npx tsc --noEmit && npm run build
```

## Ce dépôt : API et collecteur

Python 3.12, FastAPI, SQLAlchemy 2.0 asynchrone, PostgreSQL, Alembic.

```text
app/
  core/            config, database, security, deps, enums, exceptions, pagination
  auth/ user/ host/ container/ metric/
  project/         projets auto-detectes + fichiers de configuration
  live/            serie temps reel a la seconde
  energy/          model.py = modele energetique en fonctions pures, sans I/O
  config_analysis/ parsers.py, patch.py, rules.py  -- fonctions pures
  recommendation/  regles d'execution + orchestration du scan
  carbon/ comparison/ setting/
  collector/       stream.py, frame.py, aggregator.py, supervisor.py, config_reader.py
tests/             240 tests, essentiellement des fonctions pures
```

## Le collecteur

Trois boucles asyncio indépendantes, aucune n'utilise de thread :

| Boucle | Cadence | Rôle |
| --- | --- | --- |
| superviseur | 10 s | liste les conteneurs, crée les projets, ouvre et ferme les flux, lit les configs |
| flux | poussé | une connexion `stats?stream=true` par conteneur, 1 trame/s |
| agrégation | 1 s | puissance hôte, attribution, écriture `live_sample` ; tous les 10 ticks, persistance |
| purge | 60 s | supprime les mesures live au-delà de la rétention |

**Pourquoi le streaming.** `stats?stream=false` bloque 2 secondes fixes, quel que soit le nombre de
conteneurs. Le polling à la seconde est donc impossible. En streaming, `precpu_stats` est de surcroît
fiable puisque Docker le remplit avec la trame précédente.

**Puissance persistée = énergie accumulée / durée**, jamais une moyenne des puissances instantanées.
C'est ce qui rend l'invariant `Σ P_i + Overhead = P_hôte` exact par construction, y compris quand un
conteneur a manqué quelques trames.

## Points d'attention

**Mémoire = working set**, pas `memory_stats.usage` : ce dernier inclut le page cache et empêcherait
toute détection de mémoire surdimensionnée.

**Deux mesures de CPU coexistent** : `cpu_percent` relatif à la capacité de l'hôte, base de
l'attribution énergétique ; `cpu_percent_of_limit` relatif à la limite du conteneur, base des alertes
de saturation. Elles répondent à deux questions différentes.

**Identité des conteneurs** : la clé stable est `(project_id, name)`, pas l'identifiant Docker. Un
conteneur recréé garde son historique.

**Lecture des fichiers de configuration** : seul le collecteur y accède, avec l'UID de l'utilisateur
propriétaire des projets. Un garde refuse tout chemin hors de `PROJECTS_ROOT`, liens symboliques
résolus. Couvert par `tests/unit/test_config_reader.py`.

## Commandes

```bash
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload
python -m app.collector

pytest                                    # tests unitaires et d'API
black . && isort . && ruff check .
```

Les tests créent et détruisent une base `<DATABASE_NAME>_test`. Les paramètres du modèle
(facteur d'émission, puissances, pondérations, seuils, rétention) vivent en base dans `green_config`,
versionnés — ce ne sont pas des variables d'environnement.
