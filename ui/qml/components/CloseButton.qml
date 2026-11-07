import QtQuick
import QtQuick.Controls.Basic

AbstractButton {
    id: button
    width: 26; height: 26
    focusPolicy: Qt.StrongFocus
    Accessible.name: qsTr("Закрыть")
    background: Rectangle {
        radius: 6
        color: button.hovered || button.activeFocus ? "#203d668d" : "transparent"
        border.width: button.activeFocus ? 1 : 0
        border.color: "#8cdcff"
    }
    contentItem: Item {
        Rectangle {
            width: 11; height: 1; radius: 1; anchors.centerIn: parent
            color: button.hovered ? "#ffffff" : "#daeffa"; rotation: 45
            antialiasing: true
        }
        Rectangle {
            width: 11; height: 1; radius: 1; anchors.centerIn: parent
            color: button.hovered ? "#ffffff" : "#daeffa"; rotation: -45
            antialiasing: true
        }
    }
}
