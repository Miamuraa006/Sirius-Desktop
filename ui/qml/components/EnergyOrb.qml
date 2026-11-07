import QtQuick

Item {
    id: orb
    property string phase: "idle"
    property real level: 0
    property bool awake: false
    property bool animated: true
    property real time: 0
    property real smoothedLevel: 0
    property real reveal: awake ? 1 : 0
    readonly property bool gpuAvailable: GraphicsInfo.api !== GraphicsInfo.Software
    readonly property int frameCount: clock.currentFrame
    readonly property bool moving: animated && visible && (awake || reveal > 0.001)
    Behavior on reveal {
        NumberAnimation { duration: orb.awake ? 1050 : 1350; easing.type: Easing.InOutCubic }
    }
    FrameAnimation {
        id: clock
        running: orb.moving
        onTriggered: {
            var dt = Math.min(frameTime, 0.05)
            orb.time += dt
            var target = Math.max(0, Math.min(1, orb.level))
            orb.smoothedLevel += (target - orb.smoothedLevel) * (1 - Math.exp(-dt * (target > orb.smoothedLevel ? 16 : 5)))
        }
    }
    Image {
        id: referenceTexture
        source: "../../assets/hologram-reference.png"
        visible: false
        smooth: true; mipmap: true
    }
    ShaderEffect {
        id: fluid
        objectName: "fluidShader"
        anchors.fill: parent
        visible: orb.gpuAvailable && status !== ShaderEffect.Error
        property variant referenceImage: referenceTexture
        property real time: orb.time
        property real audioLevel: orb.smoothedLevel
        property real reveal: orb.reveal
        property real activity: orb.awake && (orb.phase === "processing" || orb.phase === "executing") ? 1 : 0
        property vector2d viewportSize: Qt.vector2d(width, height)
        property color accent: orb.awake && orb.phase === "error" ? "#cb719d" : appearance.colors.accent
        fragmentShader: "../../shaders/energy.frag.qsb"
    }
    // Decorative binary glyphs, not telemetry or model reasoning.
    Repeater {
        model: 7
        delegate: Text {
            required property int index
            property real orbitAngle: index * 6.283185 / 7 + orb.time * 0.075
            property real orbitRadius: orb.width * 0.405
            x: orb.width / 2 + Math.cos(orbitAngle) * orbitRadius - width / 2
            y: orb.height / 2 + Math.sin(orbitAngle) * orbitRadius * 1.02 - height / 2
            text: ((2113 + index * 397 + Math.floor(orb.time * 2)) % 65535).toString(2).slice(-5)
            textFormat: Text.PlainText
            font.family: "Consolas"; font.pixelSize: 4
            lineHeight: 1.12
            color: appearance.colors.accent
            opacity: orb.reveal * 0.24 * (0.8 + 0.2 * Math.sin(orb.time * 0.8 + index))
        }
    }
    // Software mode still has a visible character and a smooth wake / sleep transition.
    Image {
        anchors.centerIn: parent
        width: parent.width; height: width
        source: referenceTexture.source
        visible: !fluid.visible
        fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
        scale: 0.70 + orb.reveal * 0.30
        opacity: orb.reveal
    }
}
