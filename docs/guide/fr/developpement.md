# Développer et tester

[Documentation](../../README.md) · [English](../en/development.md)

[Développement](#développement) · [Traductions](#traductions) · [Tests avec des services réels](#tests-avec-des-services-réels)

## Développement

Exécutez les commandes suivantes depuis la racine du dépôt.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/torrentlinker
.venv/bin/pytest
```

Python 3.11 ou plus récent est nécessaire. Pour lancer les contrôles locaux :

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q
```

## Traductions

Les textes de l’interface sont en anglais dans le code ; leur traduction française se trouve dans `src/torrentlinker/i18n/`. Après modification d’un texte :

```bash
.venv/bin/pyside6-lupdate $(find src/torrentlinker -name "*.py") -ts src/torrentlinker/i18n/torrentlinker_fr.ts -no-obsolete
.venv/bin/pyside6-linguist src/torrentlinker/i18n/torrentlinker_fr.ts
.venv/bin/pyside6-lrelease src/torrentlinker/i18n/torrentlinker_fr.ts -qm src/torrentlinker/i18n/torrentlinker_fr.qm
```

## Tests avec des services réels

Pour tester une remise en seed avec qBittorrent, utilisez une instance temporaire accessible uniquement en local, jamais votre client habituel :

```bash
python scripts/qbit_sandbox.py /tmp/qbt-sandbox
qbittorrent-nox --profile=/tmp/qbt-sandbox &
TL_QBIT_SANDBOX=http://127.0.0.1:18080 .venv/bin/pytest tests/test_qbit_integration.py
```

Pour Deluge, utilisez un conteneur Docker temporaire qui voit un dossier temporaire sous le même chemin :

```bash
data=$(mktemp -d)
docker run -d --rm --name tl-deluge -p 127.0.0.1:18112:8112 -e PUID=$(id -u) -e PGID=$(id -g) -v "$data:$data" lscr.io/linuxserver/deluge:2.2.0
python scripts/deluge_sandbox.py http://127.0.0.1:18112
TL_DELUGE_SANDBOX=http://127.0.0.1:18112 TL_DELUGE_DATA="$data" .venv/bin/pytest tests/test_deluge_integration.py
docker stop tl-deluge
```

`tests/test_deluge_docker_paths.py` teste aussi les correspondances de chemins, avec un dossier vu comme `/data` dans Deluge. Sa docstring contient les commandes.

Transmission suit le même principe avec `scripts/transmission_sandbox.py`, `tests/test_transmission_integration.py` et `tests/test_transmission_docker_paths.py`. Leurs docstrings donnent les commandes.

Pour rechercher un vrai fichier sur c411, renseignez d’abord votre clé API dans **Paramètres → Connexions** :

```bash
TL_LIVE=1 .venv/bin/pytest tests/test_live.py -s
```

[Documentation](../../README.md) · [English](../en/development.md)
