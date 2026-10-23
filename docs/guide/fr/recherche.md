# Rechercher et télécharger

[Documentation](../../README.md) · [English](../en/search.md)

1. Saisissez un titre, choisissez une catégorie et ajustez ses filtres.
2. Double-cliquez sur un résultat pour consulter ses détails dans un onglet.
3. Choisissez le dossier de téléchargement, puis ajoutez le torrent à la file.
4. Ouvrez **File de téléchargement** et démarrez la file. **Télécharger maintenant** envoie directement le torrent sélectionné.

Captures de l’interface française en thème sombre, avec des données d’exemple.

![Recherche et filtres par catégorie](../images/recherche.png)

## Recherche et file de téléchargement

Dans **Recherche**, saisissez un titre et choisissez éventuellement une catégorie dans l’arborescence. Cliquez sur une flèche pour afficher les sous-catégories, sélectionnez une catégorie parente ou une sous-catégorie pour filtrer, ou **Toutes les catégories** pour retirer ce filtre. Les résultats viennent directement de l’indexeur, avec des boutons de pagination. Sélectionnez un ou plusieurs torrents, choisissez un dossier de téléchargement ou laissez le champ vide pour utiliser les dossiers par catégorie des Paramètres, puis cliquez sur **Ajouter la sélection à la file**.

### Filtres par catégorie

Pour c411, les catégories et les options de recherche proviennent de son API native. Sélectionnez une catégorie pour afficher ses filtres à choix multiples. Films & Vidéos propose résolution, source, HDR, codec, audio, canaux, langue et profil ; les séries proposent aussi saison et épisode. L’année, l’uploader, l’exclusivité et le tri sont disponibles dans toutes les catégories. **Effacer les filtres** réinitialise la sélection. Changer de catégorie retire les filtres incompatibles. Les autres indexeurs conservent leur recherche Torznab.

### Soins palliatifs

Le filtre de disponibilité permet d’afficher les torrents disponibles, d’inclure les **soins palliatifs**, ou de ne montrer que ces derniers. Les torrents que c411 identifie comme soins palliatifs portent une indication ; l’absence de seeders ne suffit pas à établir ce statut. Cette fonction aide à les trouver, mais ne suit pas vos récompenses personnelles de réanimation. La pagination conserve les critères soumis. Si c411 ne donne accès qu’à une partie d’un grand ensemble de résultats, l’application indique cette limite et invite à affiner les filtres.

### Comprendre les estimations et l’âge

Les résultats c411 affichent les colonnes triables **≈ Zen/jour** et **≈ Note**, également présentes dans les détails d’un torrent. La Note est le score de contribution estimé selon votre Classe, la catégorie, le nombre de seeders et la durée de seed. Pour un nouveau torrent, le calcul utilise votre Profil Zen, vos heures de seed prévues et votre nombre actuel de torrents en partage, avec une durée de seed initiale de zéro et votre présence dans le groupe de seeders. Les torrents déjà en partage conservent leur estimation et leur durée de seed actuelles. Survolez l’estimation pour en connaître les hypothèses. Les récompenses de réanimation restent distinctes.

La colonne **Âge** indique le temps écoulé depuis la publication, par exemple **2 heures** ou **3 jours**, et s’actualise chaque minute lorsque Recherche est visible. Survolez-la pour voir la date et l’heure locales exactes, issues de la date de création c411 ou de publication Torznab. Les dates absentes sont indiquées par **–**. L’en-tête trie la page courante selon l’horodatage réel ; utilisez **Plus récents** et l’ordre croissant ou décroissant pour trier la recherche sur l’ensemble des pages.

### Consulter les détails

Sélectionnez un résultat et cliquez sur **Ouvrir sur le site**, ou double-cliquez pour ouvrir sa description, ses images, son NFO et sa liste de fichiers dans un onglet. **Ouvrir dans des onglets** ouvre tous les résultats sélectionnés. Les détails ne sont chargés qu’à l’ouverture, sans téléchargement du `.torrent`. Le NFO est affiché en texte brut ; les images passent par le proxy configuré, sans identifiants de l’indexeur. Les descriptions sont centrées, tout en conservant les alignements explicitement définis. Les images jusqu’à 32 Mio sont décodées dans une limite de pixels et redimensionnées pour l’affichage. Les images indisponibles laissent place à des liens ; l’action de nouvelle tentative respecte le délai imposé par l’hébergeur et ne recharge pas les métadonnées du torrent. Les détails non pris en charge et les images manquantes restent consultables sur le site.

Chaque onglet de torrent propose aussi **Ajouter à la file** et **Télécharger maintenant**, avec un dossier de téléchargement modifiable. Télécharger maintenant envoie uniquement ce torrent au client et laisse les autres éléments de la file en attente. Les deux actions protègent contre les doublons et l’écrasement de fichiers. Pour changer la destination d’un torrent déjà dans la file, retirez-le d’abord de celle-ci.

### Gérer les onglets

Les onglets restent ouverts pendant vos recherches. Ouvrir à nouveau le même torrent sélectionne son onglet existant. Faites glisser les onglets pour les réordonner, utilisez la liste des onglets ouverts pour accéder à l’un d’eux, ou fermez-les avec ×, le clic du milieu, **Ctrl+W** ou leur menu contextuel. **Ctrl+Tab** et **Ctrl+Maj+Tab** passent d’un onglet à l’autre ; **Ctrl+F** revient au champ de recherche. Fermer un onglet ne retire ni n’arrête un téléchargement dans la file.

Sur la page principale de Recherche, **Ajouter tous les onglets à la file** ajoute les torrents ouverts et affiche la file sans démarrer les téléchargements. Le bouton **File de téléchargement** reste accessible au-dessus des onglets. **Télécharger tous les onglets** ajoute et lance cet ensemble en un clic, en laissant les autres éléments de la file en attente. Chaque onglet conserve son dossier de téléchargement. Toutes les destinations sont vérifiées avant l’ajout du lot ; en cas de problème, l’onglet concerné s’ouvre et un message apparaît au-dessus des onglets. Les onglets durent le temps de la session ; la file est conservée après redémarrage.

### Démarrer et gérer la file

![File de téléchargement](../images/file.png)

La file affiche aussi **≈ Zen/jour** et **≈ Note** pour chaque torrent. Cliquez sur leurs en-têtes pour trier numériquement. Les estimations utilisent le même calcul que les résultats de recherche et sont actualisées lorsque le Profil Zen ou les torrents en partage changent. Elles restent disponibles après redémarrage de l’application.

Dans **File de téléchargement**, cliquez sur **Démarrer la file** pour envoyer les torrents au client dans l’ordre. La file respecte les limites de téléchargement de l’indexeur et attend lorsqu’il le demande. **Pause** interrompt les prochains envois après la requête en cours ; les téléchargements déjà lancés continuent dans le client torrent. La file et les résultats sont conservés après redémarrage, mais l’envoi attend votre action pour reprendre. Les échecs peuvent être retentés ; les éléments envoyés peuvent être retirés de la liste sans supprimer les torrents du client. Les torrents déjà présents et les fichiers à destination sont protégés contre les doublons et l’écrasement.

### Torrents indisponibles

Lorsque c411 indique explicitement qu’un torrent n’est pas disponible au téléchargement, TorrentLinker le retire du Catalogue local et mémorise son hash. Les actualisations et imports du Catalogue ne le réintroduisent pas, même après redémarrage : les prochains Plans ne le proposent plus. Les erreurs d’authentification, les limites de requêtes et les erreurs du serveur ne retirent aucun torrent.

[Documentation](../../README.md) · [English](../en/search.md)
