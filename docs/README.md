# Documentation TorrentLinker

[Présentation et téléchargement](../README.md) · [English introduction](../README.en.md)

## Commencer

1. [Installer et configurer](guide/fr/demarrage.md) : première connexion, client torrent, dossiers, NAS, Docker et proxy.
2. [Bibliothèque et remise en seed](guide/fr/bibliotheque.md) : ajouter un dossier, retrouver des correspondances et vérifier les fichiers.
3. [Rechercher et télécharger](guide/fr/recherche.md) : filtres, détails, onglets et file de téléchargement.

## Aller plus loin

- [Zen et Plans](guide/fr/zen.md) : notes, gains estimés, budget et choix des torrents.
- [Préparer un upload c411](guide/fr/upload.md) : brouillons et images ; [règles par catégorie](guide/fr/upload-categories.md).
- [Données, mises à jour et dépannage](guide/fr/donnees.md).
- [Développer, traduire et tester](guide/fr/developpement.md).

Les captures montrent l’interface en français, en thème sombre, avec des données d’exemple. Ce sont des captures des composants de l’application, réalisées hors ligne ; elles ne contiennent aucun compte ni fichier personnel. Les décorations des fenêtres dépendent du système utilisé.

## English guides

- [Setup and connections](guide/en/getting-started.md)
- [Library and reseeding](guide/en/library.md)
- [Search and download queue](guide/en/search.md)
- [Zen and Plans](guide/en/zen.md)
- [Uploads and Drafts](guide/en/upload.md)
- [Data and troubleshooting](guide/en/data.md)
- [Development and testing](guide/en/development.md)

## Références techniques

- [Vocabulaire du projet](../CONTEXT.md)
- [Décisions d’architecture](adr/)
- [Recherches sur les API et règles c411](research/)
- [Notes de version](releases/)

## Actualiser les captures

Depuis la racine du dépôt, avec les dépendances de développement installées :

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_docs.py
```

Le script utilise des paramètres et une base temporaires, interdit les connexions réseau et remplace l’accès au trousseau. Il enregistre les PNG dans `docs/guide/images/`. Les autres données de l’application ne sont pas modifiées.

Pour les captures en anglais, ajoutez `--language en` à cette commande. Elles sont enregistrées dans `docs/guide/images/en/`.
