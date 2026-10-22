# One list of Path Mappings, detected from qBittorrent

Path Mappings used to belong to Library Folders: each folder said how qBittorrent sees it. Download Folders had none, so with qBittorrent in Docker or on a NAS a Plan sent this computer's path to qBittorrent, which then saved into a folder that exists only inside its container. A Docker volume or a NAS share also usually covers a whole tree, so users repeated the same mapping for every folder, and had to know how the container sees each path.

The settings now hold one list of Path Mappings, each a prefix on this computer and the same location as qBittorrent sees it. It applies to every path exchanged with qBittorrent: Library Folders, Download Folders, Reseeds and Plans. Mappings saved by earlier versions on Library Folders move into the list when settings load.

The app can propose the list itself. For each save path qBittorrent reports, it reads the files of a few torrents and looks for the largest file, by name and size, under the Library and Download Folders and a few folders above each. Where it finds one, the mapping is the part of both paths before the end they share, keeping at least one folder on each side. A check then counts, for each mapping, the qBittorrent torrents whose folder exists on this computer. When qBittorrent's own download folder does not exist here, Download Folders that no mapping covers are reported as probably unreachable by qBittorrent. Detection and checks only talk to qBittorrent, never to the Indexer.

A test runs this against qBittorrent in a throwaway Docker container that sees a host folder as `/data`.
