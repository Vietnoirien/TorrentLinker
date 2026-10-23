# Règles d’upload par catégorie

[Préparer un upload](upload.md) · [Documentation](../../README.md)

[Livres numériques](#livres-numériques) · [Audio](#audio) · [Films et vidéos](#films-et-vidéos) · [GPS et émulation](#gps-et-émulation) · [Applications](#applications) · [Jeux vidéo](#jeux-vidéo)

Les contrôles décrits ici sont ceux de TorrentLinker. Relisez les règles c411 lors de la publication ; les avertissements qui demandent un jugement restent à votre charge.

## Livres numériques

Pour **Ebook** — Livres, BDs, Comics, Manga, Presse, Audio, Partitions, Revues & Manuels — la sous-catégorie proposée est BDs pour les CBR/CBZ et dossiers d’images de pages, Audio pour les MP3/M4A/M4B/FLAC, et Livres sinon.

Les refus couvrent l’absence de fichier, les archives RAR/ZIP/7z, l’absence de format accepté et les livres audio sous 64 kbit/s, débit lu dans leurs métadonnées. Les formats acceptés comprennent PDF, EPUB, MOBI, DjVu, CBR, CBZ, JPG/PNG et les formats de livres audio. Les avertissements rappellent le français uniquement, l’absence de doublons, deux formats maximum par livre et des tomes entiers dans les packs BD/Comics/Manga, avec tous les tomes pour une BD.

Le nom suit `Titre.Auteur.FRENCH.EPUB-NOTAG`, avec titre et auteur déduits de `Auteur - Titre`. Le champ Source fournit le tag de team ; un pack ajoute `[T01.a.T07]`. La presse utilise `Titre.Date.FRENCH.PDF-NOTAG`. Le format et la langue française sont préremplis. Chargez le brouillon sur la page d’upload c411, ajoutez l’image et publiez. Voir [ADR-0011](../../adr/0011-uploads-start-as-c411-drafts.md) et le [résumé des règles](../../research/upload-rules.md).

## Audio

Pour **Audio** — Karaoké, Musique, Podcast Radio, Samples — la sous-catégorie proposée est Musique. À la sélection d’un élément, [mutagen](https://mutagen.readthedocs.io) lit en arrière-plan artiste, album, année, titres, durées, codec, débit, fréquence et profondeur de bits. Les contrôles qui en dépendent apparaissent ensuite.

Les refus couvrent l’absence d’audio, les archives, les formats non listés par c411 comme APE, Opus ou les fichiers AAC, les MP3 sous 320 kbit/s constants — le VBR est accepté — et l’AAC sous 256 kbit/s, ou 128 pour podcasts et radio. Un album en un seul fichier sans `.cue`, ou mélangeant formats ou débits, est également refusé. FLAC, ALAC, WAV, WV, AIF, MP3, M4A, OGG, WMA et ISO sont acceptés.

Les avertissements rappellent l’interdiction des transcodages, les singles à partir de 20 minutes et les discographies réservées aux artistes inactifs. Pour un CD-Rip lossless 16 bits/44,1 kHz accompagné d’un `.cue` ou `.log`, ils signalent les éléments manquants parmi `cover.jpg` d’au moins 500 × 500 pixels, le `.cue` et le journal EAC, ainsi que le numéro de catalogue et le lien Discogs ou MusicBrainz à fournir dans la description.

Le nom issu des métadonnées reste modifiable : `Daft.Punk.Discovery.2001.FLAC.16bit.44.1kHz-NOTAG`, avec `CD-Rip` après l’année si nécessaire ou `MP3.320kbps` pour une version avec pertes. Les podcasts utilisent par exemple `Emission.2024.05.12.INTEGRALE.MP3.128kbps-NOTAG`, les samples `Nom.2023.wav.1411kbps`. Le NFO récapitule les caractéristiques, la taille et les pistes avec leurs durées. Les options de format, source CD et type Album ou Discographie sont préremplies.

## Films et vidéos

Pour **Films & Vidéos**, la sous-catégorie proposée est Film, ou Série TV si le nom contient une saison ou un épisode. Les sous-catégories prises en charge comprennent aussi Animation, Animation Série, Concert, Documentaire, Série Documentaire, Émission TV, Spectacle, Sport, Vidéo-clips et Collection.

Chaque vidéo est analysée en arrière-plan avec [MediaInfo](https://mediaarea.net/en/MediaInfo), via `pymediainfo` ; voir [ADR-0012](../../adr/0012-mediainfo-through-pymediainfo.md). Si libmediainfo ne peut pas être chargée, un message demande son installation et bloque l’upload vidéo. Avec une clé TMDb dans les Paramètres, l’identification utilise un identifiant dans le nom ou le `.nfo`, sinon une recherche par titre. Le titre français alimente le nom de release, le synopsis rejoint la description, le brouillon reçoit `tmdbData` et la recherche de releases existantes utilise l’identifiant TMDb.

Les refus couvrent les archives, les conteneurs autres que MKV, MP4, M4V, AVI, TS, M2TS ou les disques ISO/BDMV/VIDEO_TS, les encodeurs GPU NVENC/QSV/AMF, les encodages sous le débit minimal c411 hors WEB-DL et remux, les teams interdites comme Wawacity, kORE ou RARBG, l’absence d’audio français et de sous-titres français complets, ainsi que les packs aux caractéristiques ou teams incohérentes.

Les avertissements concernent le titre français, les sources interdites, la plateforme VOD à préciser pour le WEB, le détag MICKEY, les épisodes manquants et la règle des 28 emplacements de doublons. Cette dernière n’est pas calculée : consultez les releases existantes.

Le nom suit les modèles c411, par exemple `Le.Film.2020.VFF.1080p.BluRay.AC3.5.1.x264-TFA`, à partir du nom de fichier et de MediaInfo : langue, résolution, source, REMUX/BDMV/ISO, HDR, audio et codec vidéo. Les encodages utilisent `x264`/`x265`, les WEB-DL `H264`/`H265`, les remux et disques `AVC`/`HEVC`. Le tag de team est conservé sans caractères spéciaux, ou remplacé par `NOTAG`. Lorsqu’un dossier contient une seule vidéo, son nom à l’intérieur du torrent reprend exactement le titre de la release. Le NFO contient le texte MediaInfo complet de chaque fichier, ou seulement du premier pour un pack de plus de dix fichiers. Il est aussi transmis dans le champ `mediainfo` du brouillon. Langue, qualité, source et codec sont préremplis lorsque les valeurs c411 le permettent.

## GPS et émulation

**GPS** — Applications, Cartes, Divers — et **Emulation** — Émulateur, ROM/ISO — se choisissent directement dans le formulaire : aucun Type de contenu ne les propose automatiquement. Les noms conservent espaces et accents là où c411 les autorise.

GPS refuse les éléments vides, archives RAR/ZIP/7z et exécutables de téléchargement ; les `.cab` d’installation et fichiers texte restent acceptés. Les avertissements demandent la version et l’activation, et rappellent l’interdiction des versions alpha ou en accès anticipé. Le nom proposé suit `Marque.Zone.Année.Support`, le support étant le système visé.

Emulation refuse les archives sauf dans un pack de plus de 50 fichiers, les ZIP protégés par mot de passe dans ces packs, les `.bin` sans `.cue` et les images CloneCD sans l’ensemble `.ccd`, `.img`, `.sub`. La protection par mot de passe n’est détectée que pour ZIP. Les avertissements concernent les plateformes rétro et le mélange de machines dans un pack, sauf MAME. Un jeu peut être nommé `[SNES]Zelda [EU - MULTI] SFC`, avec console déduite de l’extension et région/langues des indications `(Europe) (Fr,En)`.

Les deux catégories produisent un NFO factuel, un emplacement pour les instructions d’installation en français et la liste complète des fichiers.

## Applications

**Applications** comprend Autre, Formation, Linux, MacOS, Smartphone, Tablette et Windows, sans sélection automatique par Type de contenu. La sous-catégorie est déduite des fichiers : `.exe`/`.msi` pour Windows, `.dmg`/`.pkg`/`.app` pour MacOS, `.deb`/`.rpm`/`.AppImage` pour Linux, `.apk`/`.ipa` pour Smartphone, Autre sinon.

Le type de release — keygen, crack, patch, installation ou portable — est déduit des fichiers et affiché à titre indicatif ; vous pouvez le corriger en modifiant le nom. Cette table de décision est l’interprétation de TorrentLinker et **n’a pas été vérifiée contre le wiki c411**. Voir le [résumé des règles](../../research/upload-rules.md).

Les refus couvrent les archives et exécutables de téléchargement, mais acceptent les `.cab` d’installation et fichiers texte. Les avertissements concernent les instructions d’installation hors portable, l’interdiction des versions alpha, de l’accès anticipé et des logiciels IPTV, et le retrait d’une ancienne version de même génération. Le nom suit `Nom Version [OS Langue Type]`, ou `[OS] Nom Version Langue [EXT]` pour téléphone et tablette. Le NFO et la description précisent version, système, année, taille, langues, activation, prérequis et instructions d’installation en français.

## Jeux vidéo

**Jeux Vidéo** est proposé pour le Type de contenu Jeux et couvre Autre, Linux, MacOS, Microsoft, Nintendo, Smartphone, Sony, Tablette, Windows et VR. Les fichiers proposent la sous-catégorie : `.nsp`/`.xci` pour Nintendo, `.pkg` pour Sony, `.xex` pour Microsoft, `.apk` pour Smartphone, `.dmg` pour MacOS, `.AppImage` pour Linux, `.exe` pour Windows ; le nom peut indiquer la VR.

Pour un jeu PC, les fichiers de crack, `.iso`, `setup.exe` avec données `.bin`, `steam_api` ou les mentions GOG du `.nfo` servent à proposer le type : scene, repack, portable, GOG, sans DRM ou préactivé. Cette décision reste indicative et **n’a pas été vérifiée contre le wiki c411**. Voir le [résumé des règles](../../research/upload-rules.md).

Les refus couvrent les archives, sauf packs console avec une archive par jeu, les exécutables de téléchargement et les fichiers console hors conteneurs acceptés. Les avertissements rappellent les limites de releases : une scene et un repack, une release par repacker et une portable par scene, une version GOG, une version par jeu console, avec sa région PAL/EU, NTSC/US, NTSC-J/JP ou HK.

Les noms conservent espaces et accents : noms scene et repack inchangés, portable `Nom - 1.2 [Windows - FR - PORTABLE]`, GOG `Nom (4.04) [MULTI - Windows][GOG]`, préfixe `[VR]` pour la VR, console `[Switch]Zelda [EU - FR] NSP`, avec `-CUSA…` ou `-PPSA…` pour PS4 et PS5. Le `.nfo` d’origine d’une release scene est transmis après décodage de la page de caractères DOS, donc ses octets ne restent pas strictement identiques. Sinon, le NFO décrit version, système, année, taille, langues, région, crack ou loader, prérequis et instructions en français. La langue est préremplie d’après le nom.

[Préparer un upload](upload.md) · [Documentation](../../README.md)
