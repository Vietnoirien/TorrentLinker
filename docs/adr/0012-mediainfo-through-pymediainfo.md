# MediaInfo through pymediainfo, and no video upload without it

c411's video category is the strictest: names are parsed by the *arr tools, the NFO is MediaInfo's full output, and several rules (GPU encoders, minimum bitrates, French audio or subtitles, a pack's files sharing their specs) can only be checked from what is inside the files. The Films & Vidéos profile therefore reads each video file with MediaInfo.

The app uses `pymediainfo`, a binding of libmediainfo. Its Windows and macOS wheels bundle the library, and so do the current Linux x86-64 wheels; on any other platform (or a wheel built without it) the library must be installed by the user, for example from the `libmediainfo0v5` package. The PyInstaller build collects the bundled library.

When libmediainfo cannot be loaded, the video profile refuses every item with a clear message to install it, instead of crashing or guessing: a name, an NFO or a bitrate check made without MediaInfo would send c411 a Draft Team Pending refuses. The other categories do not need it and stay available.

Reading a file touches the disk and may take a moment, so it is the profile's `inspect` step, run off the GUI thread when an item is selected (like audio tags); until it ends, the rules that need MediaInfo say nothing. The NFO is MediaInfo's text with the file's name replaced by the name the file has in the torrent, so title, NFO and files agree (c411's detag rules). TMDb, when the user has a key, gives the French title the name must carry, the synopsis, and the id for c411's by-tmdb lookup of existing releases.
