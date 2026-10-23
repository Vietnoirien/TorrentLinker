# TorrentLinker

Français · [English](README.en.md)

TorrentLinker retrouve les fichiers qui ne sont plus partagés dans qBittorrent, Deluge ou Transmission, recherche des torrents correspondants auprès d’un indexeur Torznab comme c411 et les remet en seed à partir des données déjà présentes sur le disque. L’application estime aussi vos gains de Zen, prépare des plans de téléchargement et de seed, et crée des brouillons d’upload pour les contenus absents de c411. L’interface est disponible en français et en anglais.

## Télécharger la version 0.5.4

| Plateforme | Téléchargement |
| --- | --- |
| Windows x64 | [TorrentLinker.exe](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.5.4/TorrentLinker.exe) |
| Linux x86_64 | [TorrentLinker-x86_64.AppImage](https://github.com/Vietnoirien/TorrentLinker/releases/download/v0.5.4/TorrentLinker-x86_64.AppImage) |

Sous Linux, rendez l’AppImage exécutable avant de l’ouvrir. Les changements et les fichiers à télécharger figurent dans les [notes de version](https://github.com/Vietnoirien/TorrentLinker/releases/tag/v0.5.4).

TorrentLinker vérifie sur GitHub si une nouvelle version stable est disponible au démarrage, puis toutes les 30 minutes. Une vérification réussie reste en cache pendant 30 minutes. Un bandeau discret, que vous pouvez fermer, mène à la page de la nouvelle version. Le téléchargement et l’installation restent manuels. La comparaison utilise la version avec laquelle la fenêtre a démarré, même si une version plus récente est installée entre-temps. La vérification passe par votre proxy Internet, ne transmet aucune information sur votre compte ou vos torrents et reste silencieuse si GitHub est inaccessible.

## Se repérer dans l’interface

Depuis la version 0.5.0, **Recherche** rejoint les espaces **Zen**, **Bibliothèque**, **Upload** et **Paramètres**. Zen sépare **En partage**, **Plan** et **Catalogue** ; Upload sépare la préparation d’un upload et les **Brouillons**. Dans **Paramètres → Général → Thème**, choisissez Système, Clair ou Sombre. Le mode Système suit les préférences du bureau, y compris le mode sombre explicite de GNOME. Le changement de thème s’applique dès l’enregistrement.

Cliquez sur l’en-tête d’une colonne pour trier, puis une seconde fois pour inverser l’ordre. Faites glisser la séparation entre deux en-têtes pour redimensionner une colonne, ou double-cliquez pour l’ajuster au contenu. Les tailles, nombres de seeders et estimations de Zen se trient numériquement. La Bibliothèque et la liste des torrents en partage disposent aussi d’un filtre textuel. Les actions de la Bibliothèque restent au-dessus de la liste ; le menu **Analyser** contient l’analyse complète qui ignore le cache. **Ctrl+1/2/3/4** change d’espace, **Ctrl+F** place le curseur dans la recherche ou le filtre de la Bibliothèque, et **Ctrl+,** ouvre les Paramètres.

Dans la Bibliothèque, **Ajouter un dossier…** permet de choisir un dossier, son **Type de contenu** et sa **Profondeur d’analyse**, sans ouvrir les Paramètres. La profondeur 1 considère chaque fichier ou dossier directement contenu comme un Élément local. Après enregistrement, la Bibliothèque est analysée et filtrée sur le nouveau dossier. Un dossier déjà enregistré n’est pas ajouté une seconde fois.

**Vérifier tous les Candidats** examine les Candidats encore non vérifiés, y compris ceux masqués par les filtres, sans relancer les recherches ni les vérifications réussies. **Remettre en seed toutes les correspondances complètes** ajoute les correspondances confirmées au client torrent, puis lance la vérification par hash avant le seed. Ces actions s’exécutent en arrière-plan, avec une progression et un bouton d’annulation. Les erreurs sont regroupées pour permettre au traitement de continuer. Les torrents déjà présents dans le client sont signalés et comptés séparément des nouvelles remises en seed.

Si des correspondances complètes se trouvent dans des archives, une fenêtre indique leur taille après décompression. Choisissez **Décompresser et remettre en seed la sélection…** pour vérifier la destination et l’espace disponible d’une archive, ou l’action de remise en seed des correspondances prêtes pour ne traiter que les fichiers déjà décompressés. Le traitement par lot ne décompresse jamais les archives automatiquement.

## Recherche et file de téléchargement

Dans **Recherche**, saisissez un titre et choisissez éventuellement une catégorie dans l’arborescence. Cliquez sur une flèche pour afficher les sous-catégories, sélectionnez une catégorie parente ou une sous-catégorie pour filtrer, ou **Toutes les catégories** pour retirer ce filtre. Les résultats viennent directement de l’indexeur, avec des boutons de pagination. Sélectionnez un ou plusieurs torrents, choisissez un dossier de téléchargement ou laissez le champ vide pour utiliser les dossiers par catégorie des Paramètres, puis cliquez sur **Ajouter la sélection à la file**.

Pour c411, les catégories et les options de recherche proviennent de son API native. Sélectionnez une catégorie pour afficher ses filtres à choix multiples. Films & Vidéos propose résolution, source, HDR, codec, audio, canaux, langue et profil ; les séries proposent aussi saison et épisode. L’année, l’uploader, l’exclusivité et le tri sont disponibles dans toutes les catégories. **Effacer les filtres** réinitialise la sélection. Changer de catégorie retire les filtres incompatibles. Les autres indexeurs conservent leur recherche Torznab.

Le filtre de disponibilité permet d’afficher les torrents disponibles, d’inclure les **soins palliatifs**, ou de ne montrer que ces derniers. Les torrents que c411 identifie comme soins palliatifs portent une indication ; l’absence de seeders ne suffit pas à établir ce statut. Cette fonction aide à les trouver, mais ne suit pas vos récompenses personnelles de réanimation. La pagination conserve les critères soumis. Si c411 ne donne accès qu’à une partie d’un grand ensemble de résultats, l’application indique cette limite et invite à affiner les filtres.

Les résultats c411 affichent les colonnes triables **≈ Zen/jour** et **≈ Note**, également présentes dans les détails d’un torrent. La Note est le score de contribution estimé selon votre Classe, la catégorie, le nombre de seeders et la durée de seed. Pour un nouveau torrent, le calcul utilise votre Profil Zen, vos heures de seed prévues et votre nombre actuel de torrents en partage, avec une durée de seed initiale de zéro et votre présence dans le groupe de seeders. Les torrents déjà en partage conservent leur estimation et leur durée de seed actuelles. Survolez l’estimation pour en connaître les hypothèses. Les récompenses de réanimation restent distinctes.

La colonne **Âge** indique le temps écoulé depuis la publication, par exemple **2 heures** ou **3 jours**, et s’actualise chaque minute lorsque Recherche est visible. Survolez-la pour voir la date et l’heure locales exactes, issues de la date de création c411 ou de publication Torznab. Les dates absentes sont indiquées par **–**. L’en-tête trie la page courante selon l’horodatage réel ; utilisez **Plus récents** et l’ordre croissant ou décroissant pour trier la recherche sur l’ensemble des pages.

Sélectionnez un résultat et cliquez sur **Ouvrir sur le site**, ou double-cliquez pour ouvrir sa description, ses images, son NFO et sa liste de fichiers dans un onglet. **Ouvrir dans des onglets** ouvre tous les résultats sélectionnés. Les détails ne sont chargés qu’à l’ouverture, sans téléchargement du `.torrent`. Le NFO est affiché en texte brut ; les images passent par le proxy configuré, sans identifiants de l’indexeur. Les descriptions sont centrées, tout en conservant les alignements explicitement définis. Les images jusqu’à 32 Mio sont décodées dans une limite de pixels et redimensionnées pour l’affichage. Les images indisponibles laissent place à des liens ; l’action de nouvelle tentative respecte le délai imposé par l’hébergeur et ne recharge pas les métadonnées du torrent. Les détails non pris en charge et les images manquantes restent consultables sur le site.

Chaque onglet de torrent propose aussi **Ajouter à la file** et **Télécharger maintenant**, avec un dossier de téléchargement modifiable. Télécharger maintenant envoie uniquement ce torrent au client et laisse les autres éléments de la file en attente. Les deux actions protègent contre les doublons et l’écrasement de fichiers. Pour changer la destination d’un torrent déjà dans la file, retirez-le d’abord de celle-ci.

Les onglets restent ouverts pendant vos recherches. Ouvrir à nouveau le même torrent sélectionne son onglet existant. Faites glisser les onglets pour les réordonner, utilisez la liste des onglets ouverts pour accéder à l’un d’eux, ou fermez-les avec ×, le clic du milieu, **Ctrl+W** ou leur menu contextuel. **Ctrl+Tab** et **Ctrl+Maj+Tab** passent d’un onglet à l’autre ; **Ctrl+F** revient au champ de recherche. Fermer un onglet ne retire ni n’arrête un téléchargement dans la file.

Sur la page principale de Recherche, **Ajouter tous les onglets à la file** ajoute les torrents ouverts et affiche la file sans démarrer les téléchargements. Le bouton **File de téléchargement** reste accessible au-dessus des onglets. **Télécharger tous les onglets** ajoute et lance cet ensemble en un clic, en laissant les autres éléments de la file en attente. Chaque onglet conserve son dossier de téléchargement. Toutes les destinations sont vérifiées avant l’ajout du lot ; en cas de problème, l’onglet concerné s’ouvre et un message apparaît au-dessus des onglets. Les onglets durent le temps de la session ; la file est conservée après redémarrage.

Dans **File de téléchargement**, cliquez sur **Démarrer la file** pour envoyer les torrents au client dans l’ordre. La file respecte les limites de téléchargement de l’indexeur et attend lorsqu’il le demande. **Pause** interrompt les prochains envois après la requête en cours ; les téléchargements déjà lancés continuent dans le client torrent. La file et les résultats sont conservés après redémarrage, mais l’envoi attend votre action pour reprendre. Les échecs peuvent être retentés ; les éléments envoyés peuvent être retirés de la liste sans supprimer les torrents du client. Les torrents déjà présents et les fichiers à destination sont protégés contre les doublons et l’écrasement.

Lorsque c411 indique explicitement qu’un torrent n’est pas disponible au téléchargement, TorrentLinker le retire du Catalogue local et mémorise son hash. Les actualisations et imports du Catalogue ne le réintroduisent pas, même après redémarrage : les prochains Plans ne le proposent plus. Les erreurs d’authentification, les limites de requêtes et les erreurs du serveur ne retirent aucun torrent.

## Configuration initiale

Au premier lancement, ou si aucune clé API d’indexeur n’est enregistrée, un message de bienvenue ouvre les Paramètres de connexion. Les chargements automatiques attendent la configuration. Après enregistrement de la clé, l’application charge vos données sans redémarrage. Si vous annulez ou enregistrez sans clé, elle reste en attente avec un lien vers les Paramètres.

1. Activez l’interface Web de votre client torrent :
   - **qBittorrent** : **Outils → Options → Interface Web**.
   - **Transmission** 4.x : activez l’accès distant dans **Préférences → Distant**. L’ajout de `.part` aux noms des fichiers incomplets doit être désactivé pour les remises en seed, sinon Transmission renommerait vos fichiers pendant la vérification. TorrentLinker propose de désactiver cette option. Transmission ne sait renommer les fichiers et dossiers que sur place : une correspondance nécessitant une autre organisation des dossiers ne peut pas être remise en seed avec ce client. Voir [ADR-0010](docs/adr/0010-transmission-with-whole-file-names-and-in-place-renames.md).
   - **Deluge** 2.x : lancez son interface Web (`deluge-web`, port 8112 par défaut), connectez-la à son daemon et activez le plugin **Label** dans **Préférences → Plugins**. TorrentLinker utilise les labels `torrentlinker`, `torrentlinker-verifying`, `torrentlinker-partial` et `torrentlinker-zen` pour suivre ses torrents, comme il utilise les tags de qBittorrent.
2. Ouvrez **Paramètres → Connexions**, choisissez votre **Client** et renseignez sa connexion, puis l’URL et la clé API de l’indexeur. Ajoutez votre URL d’annonce pour les uploads. qBittorrent accepte un nom d’utilisateur et un mot de passe, ou une clé API d’interface Web lorsqu’elle est disponible. Deluge utilise l’adresse et le mot de passe de son interface Web. Transmission utilise son adresse distante et, si vous en avez défini, ses identifiants.
3. Ajoutez vos dossiers depuis **Bibliothèque → Ajouter un dossier…**, ou dans les Paramètres, pour trouver les fichiers à remettre en seed.
4. Définissez les dossiers de téléchargement des catégories à inclure dans les Plans, ou un dossier par défaut. Les catégories sans dossier résolu sont exclues.
5. Si votre client fonctionne dans Docker, sur un NAS ou sur un autre ordinateur, configurez **Paramètres → Chemins du client**, comme expliqué ci-dessous.

## Client torrent dans Docker, sur un NAS ou sur un autre ordinateur

Le client voit alors vos dossiers sous des chemins différents. Par exemple, un conteneur Docker voit `/data`, alors que cet ordinateur accède aux mêmes fichiers par `/mnt/nas` ou `Z:\`. TorrentLinker doit connaître cette correspondance pour reconnaître les torrents existants, remettre les fichiers en seed et envoyer les téléchargements vers un dossier accessible au client.

Dans **Paramètres → Chemins du client** :

1. Renseignez d’abord la connexion au client et vos dossiers de Bibliothèque ou de téléchargement.
2. Cliquez sur **Détecter**. TorrentLinker lit quelques torrents de chaque dossier utilisé par le client et recherche leurs fichiers par nom et taille dans vos dossiers et leurs dossiers parents. Il ajoute les correspondances trouvées, par exemple `/mnt/nas` ↔ `/data`, avec le nombre de torrents reconnus.
3. **Vérifier** compte les torrents dont le dossier existe sur cet ordinateur pour chaque correspondance. L’application signale aussi les dossiers de téléchargement probablement inaccessibles au client.
4. Enregistrez.

Vous pouvez ajouter une correspondance manuellement avec **Ajouter un dossier…** : choisissez le dossier sur cet ordinateur, puis indiquez son chemin tel que le client le voit. Une correspondance couvre tous les sous-dossiers ; si plusieurs correspondent, la plus précise s’applique.

| Installation | Sur cet ordinateur | Dans le client |
| --- | --- | --- |
| Docker local, volume `-v /srv/media:/data` | `/srv/media` | `/data` |
| Client sur NAS, partage monté sous Linux | `/mnt/nas/media` | `/volume1/media` |
| Client sur NAS, partage monté comme lecteur Windows | `Z:\` | `/volume1/media` |
| Docker sur NAS, partage monté ici | `/mnt/nas/media` | `/data` |

La détection et les vérifications communiquent uniquement avec votre client torrent.

## Proxy

Pour accéder à Internet par un proxy, renseignez **Paramètres → Connexions → Proxy** : `http://host:port`, `https://…`, `socks5://host:port` ou `socks5h://…` pour résoudre aussi les noms de domaine via le proxy. Ajoutez ses identifiants si nécessaire ; le mot de passe reste dans le trousseau système. Les connexions à c411, TMDb, au catalogue Zen Lab, aux images et au test de débit passent alors par ce proxy. Le client torrent est contacté directement, car il se trouve généralement sur cet ordinateur ou sur le réseau local, sauf si vous cochez l’option qui lui applique également le proxy. **Tester le proxy** affiche l’adresse vue par c411. Le proxy s’applique dès l’enregistrement.

## Remettre des fichiers existants en seed

Analysez la Bibliothèque, puis recherchez les Orphelins : les Éléments locaux qu’aucun torrent c411 présent dans votre client ne couvre. Les fichiers partagés uniquement sur d’autres trackers restent des Orphelins et peuvent donc être proposés pour du cross-seed sur c411. Un torrent est reconnu comme appartenant à c411 par son tracker, son hash dans le Catalogue ou un tag TorrentLinker. Le hash aide notamment lorsqu’un torrent n’a pas encore annoncé et n’indique aucun tracker. Seules les listes de fichiers de ces torrents sont lues.

TorrentLinker compare l’arborescence de chaque Candidat aux fichiers locaux. Les correspondances complètes peuvent être remises en seed sans retélécharger leurs données. Les correspondances partielles ignorent les fichiers absents et restent arrêtées après vérification.

Les chemins sont renommés à l’intérieur du client torrent : les noms et le contenu de vos fichiers sur le disque restent intacts. Une vérification par hash doit réussir avant le démarrage du seed. En cas d’échec, le torrent est retiré du client sans supprimer les fichiers locaux. Deluge reprend un torrent arrêté pendant sa vérification ; TorrentLinker limite donc sa vitesse de téléchargement à 1 octet/s jusqu’à la fin de la vérification ou au démarrage de la remise en seed, pour protéger les fichiers. Voir [ADR-0009](docs/adr/0009-deluge-through-its-web-ui-with-labels-and-a-speed-guard.md). Les recherches précédentes et les rejets sont conservés après redémarrage.

### Archives

Un Élément local au format `.zip`, `.rar` ou `.7z` est aussi comparé par son contenu, car les torrents partagent généralement les fichiers décompressés. Une correspondance affiche alors **Correspondance complète dans l’archive**. **Décompresser et repartager…** extrait les fichiers dans un nouveau dossier à côté de l’archive, après avoir indiqué la taille et l’espace libre, puis lance la remise en seed avec la vérification habituelle. Aucun fichier n’est écrasé. Une fois les fichiers vérifiés et le seed démarré, TorrentLinker propose de mettre l’archive à la corbeille ou de la conserver. Les Plans ne décompressent jamais d’archives.

Les archives ZIP ne demandent aucun outil supplémentaire. Les archives RAR et 7z nécessitent [7-Zip](https://www.7-zip.org/), ou unrar pour RAR ; sans cet outil, elles sont comparées comme de simples fichiers.

## Préparer des uploads et brouillons c411

L’onglet **Upload** affiche les Orphelins pour lesquels une recherche n’a trouvé aucune correspondance, dans tous vos dossiers de Bibliothèque. Ces contenus peuvent être absents de c411. Chaque upload appartient à une **catégorie** c411 choisie dans le formulaire. Le Type de contenu du dossier propose une catégorie : Modèles 3D → Imprimante 3D, Films et Séries → Films & Vidéos, etc. Pour le type Autre, choisissez-la vous-même. Les catégories **Imprimante 3D**, **Ebook**, **Audio**, **Films & Vidéos**, **GPS**, **Emulation**, **Applications** et **Jeux Vidéo** sont prises en charge. Les autres indiquent qu’elles ne le sont pas encore. Changer de catégorie recalcule les contrôles, la sous-catégorie, le nom, le NFO et la description.

Renseignez votre **URL d’annonce**, issue de votre profil c411, dans **Paramètres → Connexions**, et utilisez une clé API principale autorisée à gérer les **Brouillons d’upload** (`drafts:rw`). La barre de recherche au-dessus de la liste filtre les Éléments locaux par nom de fichier, en complément du Type de contenu et de **Tout afficher**.

Sélectionner un élément recherche aussi les releases que c411 possède déjà, à partir des mots de son titre et dans sa catégorie. Le bloc repliable **Déjà sur c411** affiche les résultats avec taille, seeders et lien, ou indique qu’aucun résultat n’a été trouvé. Ce résultat est informatif : Team Pending décide des doublons, pas l’application. Chaque élément n’est recherché qu’une fois par session, au moment de sa sélection, avec le même budget de requêtes que les autres recherches.

Pour la 3D, les règles vérifiables automatiquement, comme les formats acceptés et l’interdiction des archives, produisent des **Refus** rouges qui bloquent le brouillon. Les règles qui demandent votre jugement, comme l’interdiction des fichiers de créateurs indépendants qui en vivent ou la cohérence d’un pack, produisent des **Avertissements** orange sans bloquer le brouillon.

L’application propose un nom comme `Petit.Etau.De.Bureau.NOTAG.3MF`, avec des points entre les mots, sans accents et avec `NOTAG` si la source est inconnue. Elle crée un torrent privé avec la taille de pièces attendue par c411 et le champ `source = C411`, afin de conserver le même info-hash après publication, ainsi qu’un NFO listant les fichiers. Le tout est enregistré comme brouillon sur c411. Le torrent est ajouté au client avec des chemins adaptés à vos fichiers, comme pour une remise en seed, et démarre une fois la vérification réussie.

Sous la sous-catégorie, les **Options** demandées par c411 apparaissent sous forme de listes à cocher ou de menus : langue, genre, format, etc. Les options obligatoires portent un astérisque. Elles sont chargées au premier usage de la sous-catégorie et conservées une semaine ; l’action d’actualisation les recharge. Les règles peuvent préremplir certaines valeurs, mais votre choix reste prioritaire. Une option obligatoire vide bloque le brouillon. Imprimante 3D n’en demande aucune.

Ouvrez la page d’upload de c411, chargez le brouillon, ajoutez l’image demandée et publiez-le sur le site. Voir [ADR-0011](docs/adr/0011-uploads-start-as-c411-drafts.md) et le [résumé des règles](docs/research/upload-rules.md).

### Image de présentation

L’upload d’image de c411 nécessite une session de navigateur connectée. TorrentLinker peut produire l’image de vos modèles : la page **Vue 3D** affiche le modèle sélectionné, STL binaire ou ASCII, OBJ ou 3MF, sous un angle isométrique et cadré sur ses dimensions. Faites glisser pour tourner, utilisez la molette pour zoomer, puis double-cliquez ou réinitialisez la vue pour revenir au départ. Un dossier contenant plusieurs modèles propose une liste. Les gros maillages sont chargés en arrière-plan et simplifiés uniquement pour l’affichage.

- **Capturer** enregistre la vue courante en PNG, avec une largeur d’au moins 1 000 pixels.
- Pour un **Pack**, la capture de planche produit une grille d’au plus neuf modèles, chacun en vue isométrique avec son nom de fichier.
- **Ouvrir le dossier** affiche ces images, rangées dans `uploads/<release name>/`, jamais dans la Bibliothèque. Ajoutez celle de votre choix sur c411 en relisant le brouillon ; la description conserve un emplacement `[img]…[/img]`.

Si vous hébergez l’image ailleurs, collez son lien direct dans **URL de l’image**. Le bouton d’hébergement ouvre Postimages. L’image est incluse dans la description du brouillon même après modification du texte ; changer l’URL remplace l’image sans réinitialiser la présentation.

STEP, GCODE, BLEND, F3D, SLDPRT et FCStd n’ont pas d’aperçu : préparez leur image vous-même. Le rendu nécessite OpenGL ; s’il est indisponible, la vue et les captures affichent la raison de leur indisponibilité.

### Livres numériques

Pour **Ebook** — Livres, BDs, Comics, Manga, Presse, Audio, Partitions, Revues & Manuels — la sous-catégorie proposée est BDs pour les CBR/CBZ et dossiers d’images de pages, Audio pour les MP3/M4A/M4B/FLAC, et Livres sinon.

Les refus couvrent l’absence de fichier, les archives RAR/ZIP/7z, l’absence de format accepté et les livres audio sous 64 kbit/s, débit lu dans leurs métadonnées. Les formats acceptés comprennent PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG et les formats de livres audio. Les avertissements rappellent le français uniquement, l’absence de doublons, deux formats maximum par livre et des tomes entiers dans les packs BD/Comics/Manga, avec tous les tomes pour une BD.

Le nom suit `Titre.Auteur.FRENCH.EPUB-NOTAG`, avec titre et auteur déduits de `Auteur - Titre`. Le champ Source fournit le tag de team ; un pack ajoute `[T01.a.T07]`. La presse utilise `Titre.Date.FRENCH.PDF-NOTAG`. Le format et la langue française sont préremplis. Chargez le brouillon sur la page d’upload c411, ajoutez l’image et publiez. Voir [ADR-0011](docs/adr/0011-uploads-start-as-c411-drafts.md) et le [résumé des règles](docs/research/upload-rules.md).

### Audio

Pour **Audio** — Karaoké, Musique, Podcast Radio, Samples — la sous-catégorie proposée est Musique. À la sélection d’un élément, [mutagen](https://mutagen.readthedocs.io) lit en arrière-plan artiste, album, année, titres, durées, codec, débit, fréquence et profondeur de bits. Les contrôles qui en dépendent apparaissent ensuite.

Les refus couvrent l’absence d’audio, les archives, les formats non listés par c411 comme APE, Opus ou les fichiers AAC, les MP3 sous 320 kbit/s constants — le VBR est accepté — et l’AAC sous 256 kbit/s, ou 128 pour podcasts et radio. Un album en un seul fichier sans `.cue`, ou mélangeant formats ou débits, est également refusé. FLAC, ALAC, WAV, WV, AIF, MP3, M4A, OGG, WMA et ISO sont acceptés.

Les avertissements rappellent l’interdiction des transcodages, les singles à partir de 20 minutes et les discographies réservées aux artistes inactifs. Pour un CD-Rip lossless 16 bits/44,1 kHz accompagné d’un `.cue` ou `.log`, ils signalent les éléments manquants parmi `cover.jpg` d’au moins 500 × 500 pixels, le `.cue` et le journal EAC, ainsi que le numéro de catalogue et le lien Discogs ou MusicBrainz à fournir dans la description.

Le nom issu des métadonnées reste modifiable : `Daft.Punk.Discovery.2001.FLAC.16bit.44.1kHz-NOTAG`, avec `CD-Rip` après l’année si nécessaire ou `MP3.320kbps` pour une version avec pertes. Les podcasts utilisent par exemple `Emission.2024.05.12.INTEGRALE.MP3.128kbps-NOTAG`, les samples `Nom.2023.wav.1411kbps`. Le NFO récapitule les caractéristiques, la taille et les pistes avec leurs durées. Les options de format, source CD et type Album ou Discographie sont préremplies.

### Films et vidéos

Pour **Films & Vidéos**, la sous-catégorie proposée est Film, ou Série TV si le nom contient une saison ou un épisode. Les sous-catégories prises en charge comprennent aussi Animation, Animation Série, Concert, Documentaire, Série Documentaire, Émission TV, Spectacle, Sport, Vidéo-clips et Collection.

Chaque vidéo est analysée en arrière-plan avec [MediaInfo](https://mediaarea.net/en/MediaInfo), via `pymediainfo` ; voir [ADR-0012](docs/adr/0012-mediainfo-through-pymediainfo.md). Si libmediainfo ne peut pas être chargée, un message demande son installation et bloque l’upload vidéo. Avec une clé TMDb dans les Paramètres, l’identification utilise un identifiant dans le nom ou le `.nfo`, sinon une recherche par titre. Le titre français alimente le nom de release, le synopsis rejoint la description, le brouillon reçoit `tmdbData` et la recherche de releases existantes utilise l’identifiant TMDb.

Les refus couvrent les archives, les conteneurs autres que MKV, MP4, M4V, AVI, TS, M2TS ou les disques ISO/BDMV/VIDEO_TS, les encodeurs GPU NVENC/QSV/AMF, les encodages sous le débit minimal c411 hors WEB-DL et remux, les teams interdites comme Wawacity, kORE ou RARBG, l’absence d’audio français et de sous-titres français complets, ainsi que les packs aux caractéristiques ou teams incohérentes.

Les avertissements concernent le titre français, les sources interdites, la plateforme VOD à préciser pour le WEB, le détag MICKEY, les épisodes manquants et la règle des 28 emplacements de doublons. Cette dernière n’est pas calculée : consultez les releases existantes.

Le nom suit les modèles c411, par exemple `Le.Film.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA`, à partir du nom de fichier et de MediaInfo : langue, résolution, source, REMUX/BDMV/ISO, HDR, audio et codec vidéo. Les encodages utilisent `x264`/`x265`, les WEB-DL `H264`/`H265`, les remux et disques `AVC`/`HEVC`. Le tag de team est conservé sans caractères spéciaux, ou remplacé par `NOTAG`. Lorsqu’un dossier contient une seule vidéo, son nom à l’intérieur du torrent reprend exactement le titre de la release. Le NFO contient le texte MediaInfo complet de chaque fichier, ou seulement du premier pour un pack de plus de dix fichiers. Il est aussi transmis dans le champ `mediainfo` du brouillon. Langue, qualité, source et codec sont préremplis lorsque les valeurs c411 le permettent.

### GPS et émulation

**GPS** — Applications, Cartes, Divers — et **Emulation** — Émulateur, ROM/ISO — se choisissent directement dans le formulaire : aucun Type de contenu ne les propose automatiquement. Les noms conservent espaces et accents là où c411 les autorise.

GPS refuse les éléments vides, archives RAR/ZIP/7z et exécutables de téléchargement ; les `.cab` d’installation et fichiers texte restent acceptés. Les avertissements demandent la version et l’activation, et rappellent l’interdiction des versions alpha ou en accès anticipé. Le nom proposé suit `Marque.Zone.Année.Support`, le support étant le système visé.

Emulation refuse les archives sauf dans un pack de plus de 50 fichiers, les ZIP protégés par mot de passe dans ces packs, les `.bin` sans `.cue` et les images CloneCD sans l’ensemble `.ccd`, `.img`, `.sub`. La protection par mot de passe n’est détectée que pour ZIP. Les avertissements concernent les plateformes rétro et le mélange de machines dans un pack, sauf MAME. Un jeu peut être nommé `[SNES]Zelda [EU - MULTI] SFC`, avec console déduite de l’extension et région/langues des indications `(Europe) (Fr,En)`.

Les deux catégories produisent un NFO factuel, un emplacement pour les instructions d’installation en français et la liste complète des fichiers.

### Applications

**Applications** comprend Autre, Formation, Linux, MacOS, Smartphone, Tablette et Windows, sans sélection automatique par Type de contenu. La sous-catégorie est déduite des fichiers : `.exe`/`.msi` pour Windows, `.dmg`/`.pkg`/`.app` pour MacOS, `.deb`/`.rpm`/`.AppImage` pour Linux, `.apk`/`.ipa` pour Smartphone, Autre sinon.

Le type de release — keygen, crack, patch, installation ou portable — est déduit des fichiers et affiché à titre indicatif ; vous pouvez le corriger en modifiant le nom. Cette table de décision est l’interprétation de TorrentLinker et **n’a pas été vérifiée contre le wiki c411**. Voir le [résumé des règles](docs/research/upload-rules.md).

Les refus couvrent les archives et exécutables de téléchargement, mais acceptent les `.cab` d’installation et fichiers texte. Les avertissements concernent les instructions d’installation hors portable, l’interdiction des versions alpha, de l’accès anticipé et des logiciels IPTV, et le retrait d’une ancienne version de même génération. Le nom suit `Nom Version [OS Langue Type]`, ou `[OS] Nom Version Langue [EXT]` pour téléphone et tablette. Le NFO et la description précisent version, système, année, taille, langues, activation, prérequis et instructions d’installation en français.

### Jeux vidéo

**Jeux Vidéo** est proposé pour le Type de contenu Jeux et couvre Autre, Linux, MacOS, Microsoft, Nintendo, Smartphone, Sony, Tablette, Windows et VR. Les fichiers proposent la sous-catégorie : `.nsp`/`.xci` pour Nintendo, `.pkg` pour Sony, `.xex` pour Microsoft, `.apk` pour Smartphone, `.dmg` pour MacOS, `.AppImage` pour Linux, `.exe` pour Windows ; le nom peut indiquer la VR.

Pour un jeu PC, les fichiers de crack, `.iso`, `setup.exe` avec données `.bin`, `steam_api` ou les mentions GOG du `.nfo` servent à proposer le type : scene, repack, portable, GOG, sans DRM ou préactivé. Cette décision reste indicative et **n’a pas été vérifiée contre le wiki c411**. Voir le [résumé des règles](docs/research/upload-rules.md).

Les refus couvrent les archives, sauf packs console avec une archive par jeu, les exécutables de téléchargement et les fichiers console hors conteneurs acceptés. Les avertissements rappellent les limites de releases : une scene et un repack, une release par repacker et une portable par scene, une version GOG, une version par jeu console, avec sa région PAL/EU, NTSC/US, NTSC-J/JP ou HK.

Les noms conservent espaces et accents : noms scene et repack inchangés, portable `Nom - 1.2 [Windows - FR - PORTABLE]`, GOG `Nom (4.04) [MULTI - Windows][GOG]`, préfixe `[VR]` pour la VR, console `[Switch]Zelda [EU - FR] NSP`, avec `-CUSA…` ou `-PPSA…` pour PS4 et PS5. Le `.nfo` d’origine d’une release scene est transmis après décodage de la page de caractères DOS, donc ses octets ne restent pas strictement identiques. Sinon, le NFO décrit version, système, année, taille, langues, région, crack ou loader, prérequis et instructions en français. La langue est préremplie d’après le nom.

## Intégration Zen

L’onglet Zen réunit le solde fourni par c411 et les estimations de TorrentLinker :

- Lecture du Solde Zen, de la Classe, du bonus de progression débloqué et de l’autorisation de télécharger depuis votre profil c411. La clé API demande le droit `profile:read`, en plus des accès au catalogue et au téléchargement.
- Estimation du Zen/jour pour chaque torrent en partage et pour les correspondances de la Bibliothèque, selon taille, seeders, durée de seed, catégorie, bonus de Classe et heures de seed quotidiennes configurées.
- Comparaison entre Tanker, Swarm Keeper et Reuploader. Pour Reuploader, le calcul approximatif utilise le nombre d’uploads saisi dans l’onglet Zen.
- Réglage de la Classe, du bonus de progression débloqué, des heures de seed et du plafond global de torrents dans **Paramètres → Zen**. La Classe et le bonus sont remplis depuis c411 lorsque le profil est accessible.

Sans accès au profil, vous pouvez renseigner le Profil Zen manuellement et utiliser les estimations et Plans. Le solde affiché vient de c411 ; les gains prévus et le délai de rentabilisation sont des estimations locales. La durée de seed connue du client peut être inférieure à celle de c411 après suppression puis réajout d’un torrent.

### Torrents en partage par catégorie

**Zen → En partage** regroupe les torrents selon leur catégorie et sous-catégorie du Catalogue. Dépliez une branche pour voir les torrents, leur taille, leur estimation de Zen/jour et leur **≈ Note**. Les catégories affichent la moyenne arithmétique des Notes de tous leurs torrents, sous-catégories comprises ; les Notes indisponibles sont exclues. La recherche porte sur les noms de torrents et de catégories. Le tri, la largeur des colonnes, la sélection et les branches repliées sont conservés à l’actualisation. Les torrents sans catégorie connue apparaissent sous **Catégorie inconnue** ; les catégories générales issues du catalogue tiers restent au niveau parent tant qu’une sous-catégorie n’est pas confirmée.

Chaque actualisation synchronise aussi les tags de catégorie dans qBittorrent et les labels dans Transmission, par exemple `torrentlinker:category:Books / Comics`. L’application ajoute les tags manquants et remplace uniquement les anciens tags de ce préfixe, sans modifier les tags personnels, ceux de vérification, les dossiers de téléchargement ni la catégorie native du client. Les catégories inconnues ne reçoivent pas de tag. Le label unique de Deluge est conservé, car il sert à suivre la vérification ; ses torrents figurent néanmoins dans l’arborescence. La vue indique les mises à jour et leurs éventuels échecs.

## Préparer un Plan Zen

Choisissez les catégories, puis réglez le Plan :

| Réglage | Effet |
| --- | --- |
| Optimiser pour **Zen/jour** | Essaie plusieurs ordres de sélection gloutonne et garde le Plan au gain de Zen estimé le plus élevé. |
| Optimiser pour **Note** | Sélectionne d’abord les torrents aux meilleures Notes pour votre Classe. |
| Limite de téléchargement | Taille totale maximale en Go décimaux. Zéro n’ajoute aucune limite. |
| Limite de torrents | Nombre maximal facultatif de torrents ajoutés par ce Plan. |
| Peu de seeders uniquement | Nombre maximal de seeders actuels, initialement 10, avant votre arrivée. |
| Taille des torrents de… à… | Taille minimale et maximale par torrent, en Go décimaux. Zéro laisse la borne ouverte. S’applique aux téléchargements et remises en seed. |

Les remises en seed sont prioritaires. Elles comptent dans la limite de torrents mais ne consomment pas de budget de téléchargement. Le plafond global et la réserve d’espace disque s’appliquent aussi. Les résultats indiquent la Note de chaque torrent, la Note moyenne pondérée par la taille, le gain de Zen estimé, le délai de rentabilisation et l’espace libre avant et après le Plan. Les dossiers situés sur un même disque physique sont comptés ensemble. Les options sont conservées après redémarrage.

Le Plan exclut tout torrent déjà présent dans le client, quel que soit son tracker ou son état. Il exclut aussi les torrents du Catalogue dont les fichiers semblent déjà présents dans la Bibliothèque ou les dossiers de téléchargement, par exemple après suppression du torrent sans ses données. L’identification compare un Élément local ou l’un de ses fichiers à la taille du torrent, avec jusqu’à 64 Kio de moins pour un NFO ou une couverture, et exige une majorité de mots significatifs communs sans numéro de volume différent. Le résumé indique le nombre d’exclusions ; survolez-le pour les consulter. Cette étape n’effectue aucune requête. Seule une recherche dans la Bibliothèque confirme une correspondance à remettre en seed.

Chaque Plan affiche deux durées estimées. L’**envoi** au client suit les limites c411 des `.torrent` : 30 par minute et par clé API, et environ 280 sur 20 minutes. Avec davantage de clés, l’envoi accélère : environ une heure pour 1 000 torrents avec une clé, sept minutes avec cinq. Le **téléchargement** des données est estimé en divisant la taille du Plan par votre débit. **Tester le débit** utilise anonymement le test public Cloudflare pendant environ huit secondes et mémorise le résultat. Cette durée est un minimum : les torrents peu seedés peuvent être plus lents. Lancez le test lorsque votre client torrent est au repos.

L’envoi télécharge chaque `.torrent` directement depuis c411 et l’ajoute au dossier de téléchargement prévu. TorrentLinker refuse les téléchargements qui écraseraient des fichiers existants. Les remises en seed passent toujours par une vérification par hash.

Une barre de progression indique les envois, ajouts, refus et échecs, avec le temps restant estimé. **Arrêter l’envoi** s’arrête après le torrent en cours. Si c411 limite les téléchargements avec une erreur HTTP 429, l’application attend puis retente le même torrent, avec un délai croissant jusqu’à 15 minutes, et affiche l’heure de la prochaine tentative.

Le Plan et les résultats sont enregistrés au fil de l’envoi. Après un arrêt, une fermeture ou un plantage, seuls les torrents restant à envoyer reviennent ; les échecs sont retentés. Cliquez sur **Envoyer au client torrent** pour reprendre. Créer un nouveau Plan ou changer ses options remplace le Plan enregistré. Les remises en seed ne sont pas sauvegardées dans le Plan, mais passent toujours avant les téléchargements lors de l’envoi.

### Actualisation du Catalogue et estimations provisoires

Le premier Plan importe anonymement le catalogue public de métadonnées Zen Lab. Votre clé API et toutes les demandes de `.torrent` sont envoyées directement à c411.

c411 autorise 1 200 recherches et requêtes de Catalogue par heure et par compte, toutes clés confondues, et limite les téléchargements de `.torrent` à 30 par minute et par clé. TorrentLinker sépare ces budgets : les recherches vont jusqu’à deux par seconde tant que le budget horaire le permet, puis ralentissent, même pendant l’envoi d’un Plan. Chaque clé reste limitée à 30 téléchargements par minute et environ 280 sur 20 minutes. Vos recherches, vérifications de fichiers et remises en seed passent avant les Plans et actualisations du Catalogue. Si c411 impose à toutes les clés une attente supérieure à une demi-minute, les actions interactives s’arrêtent et indiquent quand réessayer.

Vous pouvez ajouter jusqu’à quatre clés du même compte dans **Paramètres → Connexions**, dans la section des clés API supplémentaires. Chacune apporte son quota de téléchargement ; les requêtes utilisent celle disponible le plus tôt. Voir [ADR-0008](docs/adr/0008-several-c411-keys-each-within-its-own-limits.md) et les [mesures de limites](docs/research/rate-limits.md).

Au démarrage et lors de la préparation d’un Plan, c411 est parcouru du plus récent au plus ancien, jusqu’au repère de la dernière actualisation réussie, ou jusqu’à une page connue lors de la première actualisation. Le parcours historique et sa pagination mémorisée sont réservés à l’action explicite de récupération du Catalogue. Les actualisations interrompues conservent leur repère et recherchent les nouveautés à la reprise.

Les Plans utilisent les métadonnées en cache et affichent des estimations provisoires. Aucun contrôle de métadonnées torrent par torrent n’est effectué auprès de c411 avant la préparation ou l’envoi. Le client torrent est interrogé toutes les 30 secondes pour actualiser la vue En partage à mesure que les trackers répondent. Les nombres de seeders connus mettent aussi à jour le Catalogue ; les valeurs inconnues conservent l’estimation en cache.

Si une actualisation est déjà en cours, le Plan l’attend puis actualise ses catégories. Un échec d’actualisation arrête sa création. Vous pouvez interrompre la récupération et créer un Plan avec les données déjà disponibles.

Le catalogue tiers fournit des catégories générales et sa fraîcheur en amont est inconnue. Ses entrées générales sont exclues d’une sélection de sous-catégorie tant que c411 n’a pas fourni une catégorie précise. Sélectionner la catégorie parente les inclut. L’actualisation des seeders ne lève pas cette incertitude. Ni les limites de pagination c411 ni ce catalogue tiers ne garantissent une couverture complète du tracker ; l’application indique les limites connues. Les valeurs de Zen restent des estimations.

Voir [CONTEXT.md](CONTEXT.md) pour le vocabulaire du projet et [docs/adr](docs/adr) pour les décisions de conception.

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
- `torrentlinker.log` : le journal, utile pour signaler un problème.

Le client torrent conserve sa propre copie des torrents ajoutés dans son dossier de profil.

## Développement

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
