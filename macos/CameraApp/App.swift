import SwiftUI
import SystemExtensions

private let extensionIdentifier = "com.hamidzr.webcam-mods.CameraExtension"

final class CameraManager: NSObject, ObservableObject, OSSystemExtensionRequestDelegate {
  @Published var status = "Activate the camera to install or update it."

  func activate() {
    submit(
      OSSystemExtensionRequest.activationRequest(
        forExtensionWithIdentifier: extensionIdentifier, queue: .main
      ))
  }

  func deactivate() {
    submit(
      OSSystemExtensionRequest.deactivationRequest(
        forExtensionWithIdentifier: extensionIdentifier, queue: .main
      ))
  }

  private func submit(_ request: OSSystemExtensionRequest) {
    request.delegate = self
    status = "Waiting for macOS..."
    OSSystemExtensionManager.shared.submitRequest(request)
  }

  func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
    status = "Allow Webcam Mods in System Settings > Privacy & Security."
  }

  func request(
    _ request: OSSystemExtensionRequest,
    actionForReplacingExtension existing: OSSystemExtensionProperties,
    withExtension extensionProperties: OSSystemExtensionProperties
  ) -> OSSystemExtensionRequest.ReplacementAction {
    .replace
  }

  func request(
    _ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result
  ) {
    status =
      result == .completed ? "Camera request completed." : "Restart Mac to complete camera request."
  }

  func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
    status = "Camera request failed: \(error.localizedDescription)"
  }
}

@main
struct WebcamModsCameraApp: App {
  @StateObject private var manager = CameraManager()

  var body: some Scene {
    WindowGroup("Webcam Mods Camera") {
      VStack(alignment: .leading, spacing: 16) {
        Text("Webcam Mods Camera").font(.title2)
        Text(manager.status).textSelection(.enabled)
        HStack {
          Button("Activate Camera") { manager.activate() }
          Button("Deactivate Camera") { manager.deactivate() }
        }
      }
      .padding(24)
      .frame(minWidth: 440)
    }
  }
}
