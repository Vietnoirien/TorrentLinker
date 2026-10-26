// The Upload tab's 3D view: one model, an orbiting camera, neutral light, a plain
// background. The interactive widget and optional OpenGL preview use this scene.
// Saved captures use the shared CPU renderer with the same Y-up camera transform.
import QtQuick
import QtQuick3D

Item {
    id: root

    property var meshGeometry: null   // a QQuick3DGeometry, centred on the origin, Y-up
    property real yaw: 45             // degrees around the vertical axis
    property real pitch: 35.264       // degrees above the horizon
    property real zoom: 1             // 1 frames the whole model
    property real baseDistance: 100   // camera distance that frames it, set from Python
    property real radius: 1           // of the model's bounding sphere
    property bool interactive: false
    property color background: "#eceff1"

    signal reset()

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: root.background
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        Node {
            // The camera and its light turn together around the model.
            eulerRotation: Qt.vector3d(-root.pitch, root.yaw, 0)

            PerspectiveCamera {
                id: camera
                z: root.baseDistance * root.zoom
                fieldOfView: 30
                clipNear: Math.max(root.radius * 0.01, 0.001)
                clipFar: root.baseDistance * 10 + root.radius * 4

                DirectionalLight {
                    // Shining from the camera's upper left: shaded sides stay readable.
                    eulerRotation: Qt.vector3d(-25, -20, 0)
                    brightness: 1.1
                    ambientColor: "#6a6a6a"
                }
            }
        }

        Model {
            visible: root.meshGeometry !== null
            geometry: root.meshGeometry ? root.meshGeometry : null
            materials: PrincipledMaterial {
                baseColor: "#a9b4bd"
                metalness: 0
                roughness: 0.65
                cullMode: Material.NoCulling
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.interactive
        property real lastX: 0
        property real lastY: 0
        onPressed: (m) => { lastX = m.x; lastY = m.y }
        onPositionChanged: (m) => {
            root.yaw -= (m.x - lastX) * 0.5
            root.pitch = Math.max(-89, Math.min(89, root.pitch + (m.y - lastY) * 0.5))
            lastX = m.x
            lastY = m.y
        }
        onWheel: (w) => {
            root.zoom = Math.max(0.15, Math.min(6, root.zoom * Math.exp(-w.angleDelta.y / 600)))
        }
        onDoubleClicked: root.reset()
    }
}
