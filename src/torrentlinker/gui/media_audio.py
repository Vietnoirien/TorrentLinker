"""Audio output construction for the native player."""

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput
from PySide6.QtQml import QQmlComponent, QQmlEngine


def create_audio_output(parent: QObject) -> QAudioOutput:
    """Create a native Qt output without PySide's virtual-method overrides.

    FFmpeg destroys its audio renderer on a worker thread. QObject cleanup calls
    the output's disconnectNotify while holding a Qt connection mutex. A
    Python-created QAudioOutput can acquire the GIL there, deadlocking with widget
    construction that holds the GIL and needs the same Qt mutex. QML constructs
    the C++ output directly; its cleanup never needs that Python override lookup.
    """
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(b"import QtMultimedia; AudioOutput {}", QUrl())
    output = component.create()
    if not isinstance(output, QAudioOutput):
        errors = "; ".join(error.toString() for error in component.errors())
        engine.deleteLater()
        raise RuntimeError(f"Could not create the native audio output: {errors}")
    output.setParent(parent)
    # Keep the QML context alive for exactly the output's lifetime. The owning
    # widget destroys the output, including this engine, on the GUI thread.
    QQmlEngine.setObjectOwnership(output, QQmlEngine.ObjectOwnership.CppOwnership)
    engine.setParent(output)
    return output
