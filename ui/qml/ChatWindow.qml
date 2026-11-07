import QtQuick
import QtQuick.Controls.Basic
import "components"

Window {
    id: chat
    objectName: "chatWindow"
    width: 360; height: 284
    property real panelScale: 1
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint
    title: "SIRIUS — Chat"
    visible: false
    onClosing: function(close) { close.accepted = false; pair.hideChat() }
    Item {
        width: 360; height: 284
        scale: chat.panelScale; transformOrigin: Item.TopLeft
        GlassPanel { anchors.fill: parent }
        MouseArea {
            x: 3; y: 3; width: parent.width - 6; height: 42
            acceptedButtons: Qt.LeftButton
            onPressed: pair.beginDrag("chat")
            onPositionChanged: if (pressed) pair.drag()
            onReleased: pair.endDrag()
            onCanceled: pair.endDrag()
        }
        Text {
            x: 14; y: 10
            text: "SIRIUS"; textFormat: Text.PlainText
            color: appearance.colors.text
            font.family: "Segoe UI"; font.pixelSize: 13; font.letterSpacing: 3.5
        }
        Text {
            x: 15; y: 29
            text: "YOUR DESKTOP ASSISTANT"; textFormat: Text.PlainText
            color: appearance.colors.muted
            font.family: "Segoe UI"; font.pixelSize: 6; font.letterSpacing: 1.6
        }
        CloseButton {
            objectName: "chatClose"
            x: 326; y: 8
            Accessible.name: qsTr("Скрыть чат")
            onClicked: pair.hideChat()
        }
        Rectangle { x: 10; y: 46; width: 340; height: 1; color: appearance.colors.rowEdge }
        ListView {
            id: messages
            objectName: "messageList"
            x: 11; y: 54; width: 338; height: 174
            clip: true; spacing: 8
            boundsBehavior: Flickable.StopAtBounds
            model: bridge.messages
            reuseItems: true
            property bool followLatest: true
            property bool latestIsHelp: false
            function positionLatest() {
                if (!followLatest || count === 0) return
                forceLayout()
                if (latestIsHelp) positionViewAtIndex(count - 1, ListView.Beginning)
                else positionViewAtEnd()
            }
            onMovementStarted: followLatest = false
            onContentHeightChanged: if (followLatest) Qt.callLater(positionLatest)
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded; width: 3
                onPressedChanged: if (pressed) messages.followLatest = false
                contentItem: Rectangle { radius: 2; color: "#4876b6d8" }
                background: Rectangle { color: "transparent" }
            }
            delegate: MessageBubble {
                required property string userText
                required property string resultText
                required property string timeText
                required property string skillName
                required property string status
                required property bool verified
                width: messages.width - 5
                command: userText; reply: resultText; stamp: timeText
                skill: skillName; outcome: status; confirmed: verified
            }
            onCountChanged: {
                followLatest = true
                Qt.callLater(positionLatest)
            }
            Connections {
                target: bridge
                function onCommandFinished(result) {
                    messages.followLatest = true
                    messages.latestIsHelp = !!(result.details && result.details.presentation === "help")
                    Qt.callLater(messages.positionLatest)
                }
                function onChatRequested(isHelp) {
                    messages.latestIsHelp = isHelp
                    Qt.callLater(messages.positionLatest)
                }
            }
        }
        Column {
            objectName: "welcomeHint"
            x: 28; y: 84; width: 304; spacing: 9
            visible: messages.count === 0
            Text {
                text: "Сириус рядом."; textFormat: Text.PlainText
                color: appearance.colors.text; font.family: "Segoe UI"; font.pixelSize: 16
            }
            Text {
                width: parent.width
                objectName: "activationHint"
                text: "Нажмите Alt + M или скажите «Сириус».\n\nНапишите help, чтобы узнать,\nчто умеет Sirius."
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: appearance.colors.muted; font.family: "Segoe UI"; font.pixelSize: 11; lineHeight: 1.3
            }
        }
        Rectangle { x: 10; y: 235; width: 340; height: 1; color: appearance.colors.rowEdge }
        CommandInput { x: 11; y: 244; width: 338; height: 30 }
    }
}
