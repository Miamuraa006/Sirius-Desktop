import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: composer
    radius: 7
    color: appearance.colors.input
    border.color: field.activeFocus ? appearance.colors.accent : appearance.colors.rowEdge
    border.width: 1
    function send() {
        if (bridge.submit(field.text)) field.clear()
    }
    ScrollView {
        x: 10; y: 3; width: parent.width - 49; height: parent.height - 6
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        TextArea {
            id: field
            objectName: "commandInput"
            selectByMouse: true
            color: appearance.colors.text
            placeholderText: qsTr("Команда или help…")
            placeholderTextColor: appearance.colors.muted
            selectedTextColor: "#ffffff"; selectionColor: "#2b649d"
            font.family: "Segoe UI"; font.pixelSize: 11
            wrapMode: TextEdit.Wrap
            background: null
            leftPadding: 0; rightPadding: 0; topPadding: 3; bottomPadding: 3
            Accessible.name: qsTr("Команда")
            Keys.onReturnPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return }
                composer.send(); event.accepted = true
            }
            Keys.onEnterPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return }
                composer.send(); event.accepted = true
            }
        }
    }
    AbstractButton {
        id: send
        objectName: "sendButton"
        anchors.right: parent.right; anchors.rightMargin: 5; anchors.verticalCenter: parent.verticalCenter
        width: 22; height: 22
        enabled: bridge.ready && field.text.trim().length > 0
        focusPolicy: Qt.StrongFocus
        Accessible.name: qsTr("Отправить команду")
        onClicked: composer.send()
        background: Rectangle {
            radius: 7
            border.width: 0.7; border.color: send.hovered || send.activeFocus ? appearance.colors.shine : appearance.colors.edge
            gradient: Gradient {
                GradientStop { position: 0; color: appearance.colors.button }
                GradientStop { position: 1; color: appearance.colors.input }
            }
            Rectangle {
                anchors.fill: parent; anchors.margins: -1
                radius: 8; color: "transparent"; border.width: 1; border.color: "#18c3e4ff"
            }
        }
        contentItem: Item {
            Image {
                anchors.centerIn: parent; width: 15; height: 15
                source: "../../assets/arrow-up.svg"
                opacity: send.enabled ? 1 : 0.42
            }
        }
    }
}
