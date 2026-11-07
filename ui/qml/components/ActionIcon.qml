import QtQuick

Item {
    id: icon
    property string skill: ""
    property bool user: false
    width: 38; height: 38
    Rectangle {
        anchors.fill: parent
        radius: icon.user ? width / 2 : 5
        gradient: Gradient {
            GradientStop { position: 0; color: appearance.colors.row }
            GradientStop { position: 1; color: appearance.colors.input }
        }
    }
    Item {
        visible: icon.user
        anchors.centerIn: parent; width: 22; height: 25; scale: icon.width / 38
        Rectangle { x: 6; y: 2; width: 10; height: 10; radius: 5; color: "#d8f7ff" }
        Rectangle { x: 2; y: 14; width: 18; height: 10; radius: 5; color: "#d8f7ff" }
        Rectangle { x: 2; y: 20; width: 18; height: 4; color: "#d8f7ff" }
    }
    Text {
        visible: !icon.user && icon.skill !== ""
        anchors.centerIn: parent
        text: ({brightness: "☀", volume: "♪", applications: "▦", windows: "▣", browser: "◎",
                media: "▶", files: "▱", clipboard: "▤", screenshot: "▧", system_monitor: "▥", help: "?"})[icon.skill] || "◇"
        textFormat: Text.PlainText
        font.family: "Segoe UI Symbol"; font.pixelSize: icon.width * 0.68
        color: "#def8ff"
    }
    Text {
        visible: !icon.user && icon.skill === ""
        anchors.centerIn: parent
        text: "✧"; textFormat: Text.PlainText
        color: appearance.colors.accent; font.pixelSize: icon.width * 0.8
    }
}
