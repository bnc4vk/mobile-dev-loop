import AVFoundation
import SwiftUI

struct CameraSurface: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 16) {
            Text("Camera")
                .font(.largeTitle)
            Text(model.cameraSurfaceLabel)
                .accessibilityIdentifier("camera-surface-label")
            Text("Permission: \(model.cameraPermission)")
                .accessibilityIdentifier("camera-surface-permission")
            Button("Refresh permission") {
                model.refreshCameraPermission()
            }
            .accessibilityIdentifier("refresh-camera-permission")
        }
        .padding()
        .onAppear {
            model.refreshCameraPermission()
        }
    }
}
