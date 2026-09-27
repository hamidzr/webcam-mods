import CoreMediaIO
import Foundation

let provider = CameraProviderSource(clientQueue: nil)
CMIOExtensionProvider.startService(provider: provider.provider)
CFRunLoopRun()
