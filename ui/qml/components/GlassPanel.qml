import QtQuick

Rectangle {
    id: glass
    radius: 12
    color: "transparent"
    antialiasing: true
    border.width: 1
    border.color: appearance.colors.edge
    gradient: Gradient {
        GradientStop { position: 0; color: appearance.colors.top }
        GradientStop { position: 0.28; color: appearance.colors.middle }
        GradientStop { position: 0.76; color: appearance.colors.middle }
        GradientStop { position: 1; color: appearance.colors.bottom }
    }
    Rectangle {
        anchors.fill: parent; anchors.margins: 1
        radius: 11
        color: "transparent"
        border.width: 0.7
        border.color: "#294cc4ff"
    }
    Rectangle {
        anchors.fill: parent; anchors.margins: 3
        radius: 9
        color: "transparent"
        border.width: 0.5
        border.color: "#0effffff"
    }
    Rectangle {
        x: 12; y: 1; width: parent.width - 24; height: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 0.28; color: appearance.colors.shine }
            GradientStop { position: 0.75; color: "#29ffffff" }
            GradientStop { position: 1; color: "transparent" }
        }
    }
    Rectangle {
        x: 2; y: 14; width: 2; height: parent.height - 28
        radius: 1
        gradient: Gradient {
            GradientStop { position: 0; color: "#6bffffff" }
            GradientStop { position: 0.35; color: "#08ffffff" }
            GradientStop { position: 0.8; color: "#05ffffff" }
            GradientStop { position: 1; color: "#44b7deff" }
        }
    }
    Rectangle {
        anchors.right: parent.right; anchors.rightMargin: 2
        y: 14; width: 1; height: parent.height - 28
        gradient: Gradient {
            GradientStop { position: 0; color: "#0affffff" }
            GradientStop { position: 0.6; color: "#20c9e5ff" }
            GradientStop { position: 1; color: "#80e9f6ff" }
        }
    }
}
