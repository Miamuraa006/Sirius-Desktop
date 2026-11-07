import QtQuick

Item {
    id: crystal
    property bool animated: true
    property string phase: "idle"
    property real level: 0
    property real breath: 0
    Image {
        anchors.fill: parent
        source: "../../assets/crystal.png"
        fillMode: Image.PreserveAspectFit
        smooth: true; mipmap: true
        scale: 1 + crystal.breath * 0.012 + (crystal.phase === "listening" ? crystal.level * 0.035 : 0)
        opacity: crystal.phase === "error" ? 0.65 : 0.92 + crystal.breath * 0.08
        Behavior on scale { NumberAnimation { duration: 95 } }
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }
    SequentialAnimation on breath {
        running: crystal.animated && crystal.visible
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 3400; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 3400; easing.type: Easing.InOutSine }
    }
}
