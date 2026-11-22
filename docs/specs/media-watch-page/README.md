# Médias with the player in the page

Design preview, not decided yet. Médias keeps its Netflix-style browsing, and the player becomes part of the
page, like YouTube, on every screen: no floating box, no separate screen.

Built only from the shared palette (`panel/base.css`), embedded in `media-watch-prototype.html`. The bottom bar
switches the layout, the device (phone, phone in landscape, computer) and Media Center (enlarged) mode. The film
is a moving gradient.

Shared by all three layouts:
- **Top bar.** It sits over the film instead of pushing the page, hides while you scroll down and comes back
  as soon as you scroll up.
- **Calm selection.** The selected film no longer stays pinned while the rows scroll; choosing another card
  fades the picture behind the title, nothing moves.
- **Player.** A tap shows −10 s, play/pause, +10 s, the timeline, full screen and ×. While a film plays, a card
  plays its film.

Layouts, `?variant=A|B|C`:
- **A · Lecteur fixé en haut.** The picture stays at the top while the details and rows scroll under it
  (YouTube on a phone).
- **B · Mini-lecteur en défilant.** The player scrolls away with the page and a mini player takes over at the
  bottom; a tap on it goes back to the top (YouTube on a computer).
- **C · Lecteur + À suivre à côté.** On a computer the player and its details on the left, what comes next on
  the right; on a phone it behaves like A.
