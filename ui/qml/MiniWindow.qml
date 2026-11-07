import QtQuick
import QtQuick.Controls.Basic
import "components"

Window {
    id: mini
    objectName: "miniWindow"
    width: 180; height: 284
    property real panelScale: 1
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    title: "SIRIUS"
    visible: false
    onClosing: function(close) { close.accepted = false; pair.hideMini() }
    Item {
        width: 180; height: 284
        scale: mini.panelScale; transformOrigin: Item.TopLeft
        GlassPanel { anchors.fill: parent }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            onPressed: pair.beginDrag("mini")
            onPositionChanged: if (pressed) pair.drag()
            onReleased: pair.endDrag()
            onCanceled: pair.endDrag()
        }
        EnergyOrb {
            id: energy
            objectName: "energyOrb"
            x: 1; y: 37; width: 178; height: 222
            phase: bridge.visualState; level: bridge.audioLevel
            awake: bridge.presence.awake
            animated: mini.visible && mini.visibility !== Window.Minimized
        }
        AbstractButton {
            id: activate
            objectName: "faceActivate"
            x: 12; y: 48; width: 156; height: 194
            Accessible.name: qsTr("Активировать Сириус — Alt + M")
            onClicked: bridge.activate()
            focusPolicy: Qt.StrongFocus
            background: Rectangle {
                radius: 12; color: "transparent"
                border.color: "#628ee8ff"; border.width: activate.visualFocus ? 1 : 0
            }
            contentItem: Item {}
            HoverHandler { cursorShape: Qt.PointingHandCursor }
        }
        AbstractButton {
            id: toggle
            objectName: "miniChatToggle"
            x: 10; y: 10; width: 27; height: 27
            Accessible.name: qsTr("Показать или скрыть чат")
            focusPolicy: Qt.StrongFocus
            onClicked: pair.toggleChat()
            background: Rectangle {
                radius: 6
                color: toggle.hovered || toggle.activeFocus ? appearance.colors.button : appearance.colors.input
                border.width: 0.7; border.color: appearance.colors.edge
            }
            contentItem: Item {
                Image { anchors.centerIn: parent; width: 19; height: 19; source: "../assets/chat.svg"; smooth: true }
            }
        }
        CloseButton {
            objectName: "miniClose"
            x: 146; y: 8
            Accessible.name: qsTr("Скрыть SIRIUS в трей")
            onClicked: pair.hideMini()
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 263
            text: ({idle: bridge.presence.awake ? "На связи" : "Ожидание", listening: "Слушаю", processing: "Думаю", not_understood: "Не расслышал", executing: "Выполняю", success: "Готово", error: "Проверь чат"})[bridge.visualState] || "S I R I U S"
            textFormat: Text.PlainText
            font.family: "Segoe UI"; font.pixelSize: 9
            color: bridge.visualState === "error" ? "#eab0c0" : appearance.colors.muted
        }
    }
}
