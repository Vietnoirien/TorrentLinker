# Abonnements RSS

Ouvrez **RSS**, sous Recherche, pour suivre des flux c411 nommés. Le bouton **S'abonner au RSS** de Recherche prépare aussi un abonnement. Prévisualisez le flux avant de l'enregistrer. Un abonnement nouveau ou dont les filtres source changent exige un aperçu réussi de la même définition dans les 15 dernières minutes. L'application réutilise la clé c411 configurée. Ne collez ni clé ni URL privée dans l'abonnement.

Un abonnement utilise une recherche par titre et des identifiants Torznab, par exemple Film `2030`, Série `5000`, Musique `3010`, Livres `7020`, ou toute l'impression 3D `8010`. Ces identifiants diffèrent des catégories natives de Recherche. Plusieurs sous-catégories natives partagent un même identifiant Torznab. RSS ne distingue donc pas les objets, personnages et packs 3D par catégorie. Les filtres natifs, année, uploader et options de catégorie, ne sont pas copiés dans le flux.

La barre latérale affiche les non lus. Tous les flux regroupe les torrents identiques par infohash. Filtrez les lignes non lues, enregistrées, présentes dans un client ou en file. La sélection permet de marquer comme lu, enregistrer, masquer, conserver une liste durable, comparer les clients ou ajouter à la file de l'application. Un double clic ouvre l'aperçu de métadonnées existant. La découverte est la première observation locale ; la publication vient de la source et peut être ancienne ou désordonnée.

L'actualisation a lieu toutes les 30 minutes par défaut, sans appel à un modèle de langage. Vous pouvez actualiser, suspendre, modifier ou supprimer un flux. Une actualisation lit au maximum trois pages de 100 lignes avec recouvrement et détecte les pages répétées. La couverture reste toujours limitée. Ni une page courte ni une page répétée ne prouve un historique complet ou une absence de lacunes. Le dernier succès, les erreurs et la limite restent affichés. À l'activation, les lignes déjà accessibles constituent la référence initiale. Les règles ne traitent que les découvertes suivantes, sauf choix explicite **Inclure les torrents actuels**.

## Modes de règle

- **Lecture seule** découvre les torrents pour votre examen.
- **File de l'application** enregistre les résultats dans TorrentLinker. Ce mode ne contacte jamais un client et ne télécharge aucun fichier `.torrent`. Comparez explicitement les clients pour fournir un inventaire local récent. Un inventaire absent ou périmé bloque les décisions. La file peut dépasser l'espace disque ou les limites journalières.
- **Téléchargements automatiques** utilise la même file, puis les contrôles existants de permissions, octets et nombre de torrents journaliers, et réserve disque. Choisissez le client cible et l'un de ses dossiers configurés. La règle ne modifie aucun dossier global. Définissez les heures UTC autorisées et cochez l'autorisation explicite. Une demande de l'assistant exige toujours l'approbation du propriétaire pour activer ou modifier ce mode. Les entrées attendent lorsque les limites ou l'horaire empêchent leur démarrage. Un échec ou un envoi incertain nécessite un examen ; aucun envoi incertain n'est relancé automatiquement.

L'origine d'une entrée conserve l'abonnement, le mode, l'identité de l'œuvre et la raison du choix. Les décisions expliquent la référence initiale, les métadonnées manquantes, les doublons, l'attente, les alternatives et la mise en file. L'espace et les limites sont contrôlés au démarrage du téléchargement.

## Préférences de version

La plage de taille, la taille maximale, le minimum de seeders et les métadonnées `required` ou `excluded` sont des contraintes obligatoires. Les listes `preferred` classent les versions acceptables. Réordonnez `priorities` pour choisir le critère prioritaire. `prefer_small` classe les petites tailles au rang du critère `size`.

Ajoutez `seeders` à `priorities` pour privilégier les torrents les mieux partagés. Sa position détermine si la disponibilité prime sur la qualité, le codec ou la taille. Les nombres de seeders inconnus passent après les nombres connus. Cette préférence est distincte du minimum obligatoire `min_seeders`.

Les champs disponibles sont `quality`, `codec`, `audio`, `subtitles`, `format`, `bitrate`, `platform` et `license`. Seules des données structurées vérifiées comptent. Le titre, la description, le NFO ou une langue générale ne prouvent pas la langue audio ou des sous-titres. Une information obligatoire inconnue bloque la règle. Une préférence inconnue est classée après les valeurs préférées connues. Les critères propres à la musique, aux livres et à la 3D restent bloqués si la source ne fournit pas la donnée vérifiée.

Par exemple, pour accepter 1080p et 720p, préférer 1080p et HEVC, accepter H264, exclure CAM et AV1, et exiger l'audio français vérifié :

```json
{
  "min_size": 0,
  "max_size": 8000000000,
  "min_seeders": 3,
  "required": {"quality": ["1080p", "720p"], "codec": ["HEVC", "H264"], "audio": ["fr"]},
  "excluded": {"quality": ["CAM"], "codec": ["AV1"]},
  "preferred": {"quality": ["1080p", "720p"], "codec": ["HEVC", "H264"]},
  "priorities": ["quality", "codec", "audio", "subtitles", "size"],
  "prefer_small": true
}
```

L'aperçu expose les exclusions, informations inconnues, rangs déterministes et identifiants d'œuvre. Une attente de zéro minute choisit la première version observée admissible. Un délai plus long rassemble les alternatives avant le choix. L'infohash identifie exactement un torrent ; le regroupement par œuvre exige un identifiant fiable du film, de l'épisode ou un identifiant vérifié dans un espace de noms approprié. Les noms semblables ne sont jamais fusionnés. Une identité inconnue bloque la règle ; vous pouvez toujours examiner et mettre le torrent en file manuellement.

La comparaison reconnaît les infohashes dans les clients configurés et activés, et conserve les identifiants d'œuvre indépendamment de la visibilité dans les flux. Une recherche bornée de métadonnées peut identifier les versions déjà présentes dans les clients. Une identité encore inconnue dans un client ou la file bloque la sélection automatique jusqu'à une comparaison complète. Le titre ne comble jamais cette lacune. L'examen et la mise en file manuels restent disponibles.

**Remplacer par un meilleur choix uniquement en attente** peut remplacer une entrée encore en attente créée par la même règle. La prise en charge avant envoi est atomique. Aucun téléchargement démarré, envoyé, en échec ou incertain n'est remplacé silencieusement. Les règles n'effectuent aucune mise à niveau des téléchargements existants.

Les critères préférés absents de `priorities` sont ajoutés à la fin, dans leur ordre déclaré : une préférence de format ou de plateforme reste donc effective. Il en va de même pour `size` lorsque `prefer_small` est activé.

## Assistant et MCP

`list_feeds`, `preview_feed`, `refresh_feed`, `feed_inbox` et `compare_feed_clients` permettent l'inspection. `select_feed_items` conserve une sélection exacte et durable ; `get_feed_selections` retrouve son identifiant après une perte de contexte. `process_feed_action` enregistre, modifie, suspend ou supprime les abonnements, marque les lignes, évalue les règles et met une sélection en file selon les permissions existantes. Utilisez des identifiants de requête stables pour les modifications. Les filtres natifs de Recherche ne sont pas des paramètres RSS. L'actualisation et l'envoi automatiques ne font aucun appel à un modèle de langage.
