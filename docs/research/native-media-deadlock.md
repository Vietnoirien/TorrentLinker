# Native media cleanup deadlock

Investigated on 2026-10-30 for [#44](https://github.com/Vietnoirien/TorrentLinker/issues/44).

The investigation reproduced a Qt/PySide lock inversion during audio cleanup and widget construction. Creating the audio output through Qt's QML factory avoids the Python virtual-method lookup responsible for that inversion. The native player now uses that factory.

## What freezes

Two threads wait for each other:

1. The GUI thread holds Python's global interpreter lock, the GIL, while constructing a widget. Qt styling needs a connection mutex.
2. The FFmpeg audio renderer is being destroyed on its worker thread. Qt holds a connection mutex while notifying the audio output that a signal connection was removed. PySide's wrapper checks whether Python overrides `disconnectNotify`, which needs the GIL.

Neither thread can release its lock until the other proceeds. A Python watchdog thread cannot recover this deadlock because it also needs the GIL.

The original combined-suite capture stopped at eight native frames per thread. It showed styling/`QObject::disconnect` on the GUI thread and `take_gil` on the audio thread, but did not expose the audio caller. New captures include the missing frames:

```text
Audio: QFFmpeg::AudioR
  QObject::~QObject
  QtMultimedia Python wrapper
  Sbk_GetPyOverride
  Shiboken::GilState::acquire
  PyGILState_Ensure -> take_gil

GUI: construction of QPushButton
  Qt widget styling
  QObject::connectImpl
  QBasicMutex::lockInternal
```

The new trigger blocks in connection creation; the old capture blocked in disconnection. Both use Qt's connection mutexes. Qt 6.12 has a pool of 131 such mutexes, selected by object address, so otherwise unrelated widgets and audio objects can contend. This helps explain why long runs, allocation order and timing affect reproduction. The old truncated capture cannot establish the identity of its audio output independently, but the reproduced lock cycle matches both original wait sites.

The relevant upstream implementation is [Qt 6.12.0's QObject destructor and connection mutex pool](https://github.com/qt/qtbase/blob/v6.12.0/src/corelib/kernel/qobject.cpp). The destructor calls a sender's `disconnectNotify` while holding the receiver's connection lock. Qt also documents the threading and locking restrictions of [connection notifications](https://doc.qt.io/qt-6/qobject.html#connectNotify).

## Reproduction and controls

Environment: Linux, offscreen Qt platform, Python 3.13.11, PySide/Qt 6.12.0 and Qt's FFmpeg 9.0.1 backend. Generated silent WAV files were the only playback inputs. No tracker or Torrent Client was involved.

- Ten application playback runs completed 1,000 Media-view construction/teardown cycles without freezing.
- Fifty application restart runs completed 1,500 restart/layout cycles without freezing. These green runs alone did not establish a fix.
- Creating widgets immediately after stopping audio reproduced the deadlock twice. The external watchdog detected a stopped GUI heartbeat and only then attached GDB, capturing full stacks.
- A smaller standalone Qt program reproduced it without TorrentLinker services, pytest or application callbacks. It constructs a Python `QMediaPlayer` and `QAudioOutput`, plays a WAV, stops, then creates styled buttons.
- Disabling Python garbage collection still reproduced it. This rules out garbage collection as a necessary cause in the minimized case.
- Replacing only the output with a Qt-created `AudioOutput` completed 100 cycles. The Python player, playback input and widget construction stayed the same.
- One earlier run with a live debugger attached stalled, but its capture conflicted with that debugger. That run is inconclusive and is not counted as a reproduction.

The stress loop widens Python's scheduling interval to 50 ms inside its isolated process. A separate baseline run also froze at the normal 5 ms interval, with the same native stacks. The application keeps Python's normal scheduling policy.

## Change and regression

`gui/media_audio.py` creates `AudioOutput` with `QQmlComponent`. This creates the C++ object directly, avoiding PySide's virtual-method override on audio cleanup. The app still uses the same `QMediaPlayer`, output interface, volume/mute controls and playback state. The output belongs to the Media view, and its QML engine belongs to the output so both are destroyed together on the GUI thread. No private PySide cache or timing delay is used as a workaround.

Qt's [component creation API](https://doc.qt.io/qt-6/qqmlcomponent.html#create) provides the factory. QML support was already included for the app's model viewer. The packaged smoke check now also constructs the audio output, detecting a missing QtMultimedia QML plugin before release.

The regression runs real playback and widget construction in a subprocess. A parent timeout can terminate a deadlocked child even when the GUI holds the GIL. Its 80 cycles check playback advancement, volume/mute, stopping, parent ownership and destruction of the output's children. Before the workaround, the test froze on cycle 0 and failed at its 30-second deadline. Afterward, the regression and native playback, track and lifecycle tests passed together: 29 tests in 41.57 seconds.

The final combined run added preceding GUI workflows, theme changes and packaging-smoke checks: all 115 tests passed in 75.88 seconds. This includes a second 80-cycle pass of the new regression, with explicit checks that the output and its children are destroyed. Ruff, formatting of 395 files, mypy over 200 source files and the diff check passed.

Local captures and experimental scripts are retained in `/tmp/tl-media-freeze/`. The regression is retained in `tests/test_media_audio.py`; run it with:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_media_audio.py -q
```

The [package and recovery follow-up](recovery-audit.md) subsequently verified real playback and shutdown in the frozen Linux executable and three isolated AppImage runs. It also found and fixed a separate desktop-worker teardown failure. Windows/macOS packages, the official Linux release-runner build, graphical desktop behavior and other Qt versions still need validation.
