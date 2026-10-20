SEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
<channel>
  <item>
    <title>Le.Joueur.D'echecs.Stefan.Zweig.2013.FR.[EPUB]-NOTAG</title>
    <guid>https://c411.example/torrents/42</guid>
    <link>https://c411.example/torrents/42</link>
    <size>67163</size>
    <enclosure url="https://c411.example/api/download/42?apikey=K" length="67163"
               type="application/x-bittorrent"/>
    <torznab:attr name="seeders" value="12"/>
    <torznab:attr name="infohash" value="abcdef0123456789abcdef0123456789abcdef01"/>
    <torznab:attr name="category" value="7000"/>
  </item>
  <item>
    <title>Stefan.Zweig.Integrale.FR.EPUB</title>
    <link>https://c411.example/torrents/43</link>
    <size>9000000</size>
    <enclosure url="https://c411.example/api/download/43?apikey=K"/>
    <torznab:attr name="seeders" value="3"/>
  </item>
</channel>
</rss>
"""

CAPS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<caps>
  <searching>
    <search available="yes" supportedParams="q"/>
    <tv-search available="yes" supportedParams="q,season,ep,imdbid,tmdbid"/>
    <movie-search available="yes" supportedParams="q,imdbid,tmdbid"/>
    <book-search available="yes" supportedParams="q"/>
  </searching>
  <categories>
    <category id="2000" name="Films">
      <subcat id="2030" name="Films étrangers"/>
    </category>
    <category id="7000" name="Ebook"/>
  </categories>
</caps>
"""
