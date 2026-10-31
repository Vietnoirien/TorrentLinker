# Données, mises à jour et dépannage

[Documentation](../../README.md) · [English](../en/data.md)

[Mises à jour](#mises-à-jour) · [Avant de signaler un problème](#avant-de-signaler-un-problème) · [Emplacement des données](#emplacement-des-données)

## Mises à jour

TorrentLinker vérifie sur GitHub si une nouvelle version stable est disponible au démarrage, puis toutes les 30 minutes. Une vérification réussie reste en cache pendant 30 minutes. Un bandeau discret, que vous pouvez fermer, mène à la page de la nouvelle version. Le téléchargement et l’installation restent manuels. La comparaison utilise la version avec laquelle la fenêtre a démarré, même si une version plus récente est installée entre-temps. La vérification passe par votre proxy Internet, ne transmet aucune information sur votre compte ou vos torrents et reste silencieuse si GitHub est inaccessible.

## Avant de signaler un problème

Vérifiez la connexion au client et à l’indexeur dans les Paramètres. Pour un NAS ou Docker, vérifiez aussi les [correspondances de chemins](demarrage.md). Indiquez votre version, votre système, le client torrent et les étapes qui reproduisent le problème dans un [ticket GitHub](https://github.com/Vietnoirien/TorrentLinker/issues). Joignez le message exact ou le journal après avoir masqué les clés API, mots de passe et URL d’annonce privées.

Sur ordinateur, utilisez **Paramètres → Général → Exporter le rapport de diagnostic…**. Dans le navigateur, ouvrez **Paramètres → Interface → Exporter le rapport de diagnostic…**. Le fichier JSON contient les versions de l’application et du système, les types de clients, les formats des correspondances de chemins, les compteurs de configuration, les états des files et les types et résultats des 20 tâches les plus récentes. Les noms et identifiants des clients sont remplacés par des alias propres au rapport. Les identifiants de connexion, adresses de serveurs, chemins, noms de torrents, conversations et journaux bruts sont exclus. L’export ne contacte pas vos clients, ne relance aucune tâche et n’envoie le fichier nulle part. Vous choisissez de le joindre ou non à votre signalement.

Ce rapport décrit l’état actuel de l’application. Il ne mesure pas l’espace disque disponible et ne vérifie pas les correspondances de chemins. Sur ordinateur, l’historique des tâches est inclus quand le service local des agents fonctionne ; sinon, `recent_jobs` vaut `null`. Les étapes de reproduction et le message d’erreur visible restent utiles pour trouver la cause.

## Sauvegarder avant une mise à jour

1. Terminez ou annulez les opérations actives, puis quittez TorrentLinker. Avec Docker, arrêtez le service TorrentLinker et attendez son arrêt. Une copie réalisée pendant que l’application écrit dans ses bases n’est pas la procédure testée ici.
2. Copiez **tout le dossier de données**, sous-dossiers compris, vers une sauvegarde datée située ailleurs. Utilisez l’emplacement de bureau indiqué ci-dessous, le dossier `--config` du serveur ou le volume Docker monté sur `/config`. Conservez les permissions et tous les fichiers, y compris les éventuels journaux SQLite. Copiez le dossier entier plutôt qu’une sélection de bases.
3. Conservez séparément la configuration du déploiement et les fichiers de secrets ou de mot de passe fournis au serveur. Sur ordinateur, les identifiants sont dans le trousseau du système, hors de ce dossier. Sur un nouvel ordinateur ou compte système, saisissez-les à nouveau. Sur le serveur web, `credentials.key` et `credentials.enc` doivent rester ensemble dans la sauvegarde ; les secrets fournis par fichier doivent conserver leurs montages.
4. Installez la nouvelle version et rouvrez le même dossier de données. Vérifiez le client sélectionné, les Dossiers de téléchargement, les Brouillons locaux, les conversations et les files avant de lancer de nouvelles opérations. Un téléchargement interrompu pendant son envoi doit demander une vérification du client, sans nouvel envoi automatique.

La sauvegarde contient des conversations privées, la configuration des clients et, sur le serveur web, des identifiants déchiffrables. Gardez-la privée. Le rapport de diagnostic ci-dessus est un fichier distinct et limité, destiné au partage. La sauvegarde ne contient ni vos médias ni la configuration propre au client torrent ; sauvegardez-les séparément si nécessaire.

## Restaurer une sauvegarde

Arrêtez d’abord TorrentLinker. Gardez une copie séparée du dossier actuel, puis remettez la sauvegarde complète à son emplacement d’origine, avec ses propriétaires et permissions d’origine. Ne mélangez pas des bases provenant de sauvegardes différentes. Rouvrez avec la version qui a créé la sauvegarde ou une version dont la mise à niveau a été vérifiée. Faire lire une base déjà migrée par une ancienne version n’est pas une procédure de retour arrière testée.

Conservez les mêmes montages des Dossiers de bibliothèque et de téléchargement pour que les chemins enregistrés désignent toujours les mêmes fichiers. Vérifiez les identifiants et les connexions, puis comparez les actions en attente ou incertaines avec le client torrent ou c411 avant de réessayer. Restaurer les données de l’application n’annule pas les téléchargements ou envois de brouillons acceptés depuis la sauvegarde. Revoyez les tâches planifiées actives avant de reprendre une utilisation sans surveillance.

## Emplacement des données

| Système | Dossier |
| --- | --- |
| Linux | `~/.local/share/TorrentLinker/TorrentLinker/` |
| Windows | `%APPDATA%\TorrentLinker\TorrentLinker\`, soit `C:\Users\<vous>\AppData\Roaming\TorrentLinker\TorrentLinker\` |

Ce dossier contient :

- `torrents/` : tous les `.torrent` téléchargés, pour éviter de les demander deux fois, même après redémarrage ou reprise d’un Plan. Leur nom est une empreinte de l’adresse de téléchargement, sans votre clé. Supprimer ce dossier est sans danger : les fichiers seront récupérés à nouveau au besoin.
- `uploads/` : les `.torrent` et `.nfo` de chaque upload, tels qu’envoyés dans le brouillon, et un dossier par upload pour ses captures d’images.
- `state.db` : Catalogue, recherches mémorisées, rejets, vérifications en cours, Plan enregistré, uploads réalisés et options de catégories c411.
- `settings.json` : vos paramètres. Les clés API et mots de passe restent dans le trousseau système, pas dans ce fichier.
- `assistant.sqlite`, `agents.sqlite`, `jobs.sqlite` et les autres bases : conversations, permissions, historique des tâches et états des fonctionnalités. Le serveur web utilise `catalogue.sqlite` pour les données conservées dans `state.db` sur ordinateur. Gardez tout le dossier pour préserver cet ensemble.
- `torrentlinker.log` : le journal, utile pour signaler un problème.

Le client torrent conserve sa propre copie des torrents ajoutés dans son dossier de profil.

[Documentation](../../README.md) · [English](../en/data.md)
