import QtQuick

Item {
    id: bubble
    property string command: ""
    property string reply: ""
    property string stamp: ""
    property string skill: ""
    property string outcome: "processing"
    property bool confirmed: false
    readonly property bool isHelp: skill === "help"
    height: userRow.height + 4 + resultRow.height
    Rectangle {
        id: userRow
        width: parent.width; height: Math.max(27, userText.implicitHeight + 12)
        radius: 7; color: appearance.colors.row
        ActionIcon { x: 7; y: (parent.height - height) / 2; user: true; width: 20; height: 20 }
        Text {
            id: userText
            x: 33; y: 6; width: parent.width - 70
            text: bubble.command; textFormat: Text.PlainText
            color: appearance.colors.text; font.family: "Segoe UI"; font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter
            text: bubble.stamp; textFormat: Text.PlainText
            color: appearance.colors.muted; font.family: "Segoe UI"; font.pixelSize: 8
        }
    }
    Rectangle {
        id: resultRow
        y: userRow.height + 4
        width: parent.width; height: Math.max(35, resultText.implicitHeight + 14)
        radius: 7
        color: appearance.colors.reply
        border.width: 1
        border.color: bubble.outcome === "failed" || bubble.outcome === "unsupported" || bubble.outcome === "not_understood" ? "#78794158" : appearance.colors.rowEdge
        ActionIcon { x: 7; y: 7; width: 21; height: 21; skill: bubble.skill }
        Text {
            id: resultText
            x: 34; y: 7; width: parent.width - (bubble.isHelp ? 45 : 89)
            text: bubble.reply !== "" ? bubble.reply : qsTr("Выполняется…")
            textFormat: Text.PlainText
            color: bubble.outcome === "failed" || bubble.outcome === "unsupported" || bubble.outcome === "not_understood" ? "#ffb4c0" : appearance.colors.text
            font.family: "Segoe UI"; font.pixelSize: 11
            lineHeight: bubble.isHelp ? 1.25 : 1
            wrapMode: Text.Wrap
        }
        Rectangle {
            x: parent.width - 48; y: (parent.height - 13) / 2
            width: 13; height: 13; radius: 7
            visible: !bubble.isHelp && bubble.confirmed && bubble.outcome === "success"
            color: "transparent"; border.color: "#37e3e4"; border.width: 1
            Text {
                anchors.centerIn: parent; text: "✓"; textFormat: Text.PlainText
                color: "#4cedeb"; font.family: "Segoe UI"; font.pixelSize: 10
            }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter
            visible: !bubble.isHelp
            text: bubble.stamp; textFormat: Text.PlainText
            color: appearance.colors.muted; font.family: "Segoe UI"; font.pixelSize: 8
        }
    }
}
