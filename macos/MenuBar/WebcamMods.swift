import SwiftUI
import AVFoundation
import AppKit

struct Camera: Decodable, Identifiable {
    let index: Int
    let name: String
    let id: String
}

struct Configuration: Codable, Equatable {
    var input_device = 0
    var camera_id: String?
    var output_width: Int?
    var output_height: Int?
    var output_fps: Double?
    var width = 640
    var height = 480
    var fps = 30.0
    var effect = "plain"
    var brightness = 0
    var blur_kernel = 31
    var color = 192
    var image_path = ""
    var track = false
    var segmentation = "mediapipe"
    var processing = "opencv"
    var capture = "avfoundation"
    var repeat_frames = true
    var processing_fps = 30.0
    var smoothing = false

    var json: [String: Any] {
        (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(self))) as? [String: Any] ?? [:]
    }
}

struct ProfileIssue: Decodable {
    let name: String
    let error: String
}

struct Profile: Decodable, Identifiable {
    let name: String
    let config: Configuration
    var id: String { name }
}

@MainActor
final class SessionModel: ObservableObject {
    static weak var current: SessionModel?
    @Published var config = Configuration()
    @Published var cameras: [Camera] = []
    @Published var profiles: [Profile] = []
    @Published var selectedProfile = ""
    @Published var profileName = ""
    @Published var state = "idle" {
        didSet { if state != "running" { clearPreview() } }
    }
    @Published var outputMode = "preview"
    @Published var previewImage: NSImage?
    @Published var previewError: String?
    private var previewPending = false
    private var previewVisible = false
    private var previewGeneration = 0
    @Published var error: String?
    @Published var connected = false
    @Published var inventoryPending = false
    @Published var backendVersion = ""
    @Published var profileWarning: String?
    private var inventoryGeneration = 0
    private var inventoryCapture: String?
    private var process: Process?
    private var input: FileHandle?
    private var nextID = 0
    private var pending: [Int: (Result<Any, Error>) -> Void] = [:]
    private var outputBuffer = Data()
    private var diagnosticBuffer = Data()
    private var quitting = false
    private var startGeneration = 0
    private var workerGeneration = 0

    init() { Self.current = self }
    var hasWorker: Bool { process != nil }

    var profileModified: Bool {
        guard let saved = profiles.first(where: { $0.name == selectedProfile }) else { return false }
        var current = config
        var original = saved.config
        if current.camera_id != nil && current.camera_id == original.camera_id {
            current.input_device = 0
            original.input_device = 0
        }
        return current != original
    }
    var cameraUnavailable: Bool {
        guard !inventoryPending, inventoryCapture == config.capture else { return true }
        if let id = config.camera_id { return !cameras.contains(where: { $0.id == id }) }
        return !cameras.contains(where: { $0.index == config.input_device })
    }
    var selectedCameraID: String {
        config.camera_id ?? cameras.first(where: { $0.index == config.input_device })?.id ?? ""
    }
    func selectCamera(_ id: String) {
        guard !inventoryPending, inventoryCapture == config.capture, let camera = cameras.first(where: { $0.id == id }) else { return }
        config.camera_id = camera.id
        config.input_device = camera.index
    }
    func reconcileCamera() {
        guard !inventoryPending, inventoryCapture == config.capture else { return }
        if let id = config.camera_id, let camera = cameras.first(where: { $0.id == id }) {
            config.input_device = camera.index
        } else if config.camera_id == nil, let camera = cameras.first(where: { $0.index == config.input_device }) {
            config.camera_id = camera.id
        }
    }
    private func clearPreview() {
        previewGeneration += 1
        previewImage = nil
        previewError = nil
    }

    func pollPreview(visible: Bool) {
        if previewVisible != visible {
            previewVisible = visible
            if !visible { clearPreview() }
        }
        guard visible, connected, state == "running", !previewPending else { return }
        previewPending = true
        let generation = previewGeneration
        request("preview.get") { [weak self] result in
            guard let self else { return }
            self.previewPending = false
            guard self.previewVisible, self.state == "running", generation == self.previewGeneration else { return }
            self.acceptPreview(result)
        }
    }

    private func acceptPreview(_ result: Result<Any, Error>) {
        do {
            let value = try result.get()
            if value is NSNull { return }
            guard let frame = value as? [String: Any],
                  let width = frame["width"] as? Int, (1...640).contains(width),
                  let height = frame["height"] as? Int, (1...480).contains(height),
                  let jpeg = frame["jpeg"] as? String, jpeg.utf8.count <= 699_052,
                  let data = Data(base64Encoded: jpeg), data.count <= 524_288,
                  let bitmap = NSBitmapImageRep(data: data),
                  bitmap.pixelsWide == width, bitmap.pixelsHigh == height,
                  let image = bitmap.cgImage else {
                throw failure("Invalid preview frame. Reinstall app if this repeats.")
            }
            previewImage = NSImage(cgImage: image, size: NSSize(width: bitmap.pixelsWide, height: bitmap.pixelsHigh))
            previewError = nil
        } catch { previewError = error.localizedDescription }
    }

    func reconnect() {
        guard process == nil, !quitting else { return }
        startGeneration += 1
        inventoryGeneration += 1
        inventoryPending = false
        inventoryCapture = nil
        cameras = []
        backendVersion = ""
        outputBuffer.removeAll()
        diagnosticBuffer.removeAll()
        pending.removeAll()
        error = nil
        state = "idle"
        connect()
    }

    var active: Bool { ["starting", "running", "stopping"].contains(state) }
    var build: String {
        let info = Bundle.main.infoDictionary ?? [:]
        return "\(info["CFBundleShortVersionString"] as? String ?? "unknown") (\(info["BuildCommit"] as? String ?? "unknown"))"
    }
    var buildDate: String { Bundle.main.object(forInfoDictionaryKey: "BuildDate") as? String ?? "unknown" }

    func connect() {
        guard process == nil else { return }
        workerGeneration += 1
        let generation = workerGeneration
        do {
            guard let runtimeURL = Bundle.main.url(forResource: "backend-python", withExtension: "txt") else {
                throw failure("Python runtime missing. Rebuild app with macos/build-menu-app.sh.")
            }
            let runtime = try String(contentsOf: runtimeURL, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            guard FileManager.default.isExecutableFile(atPath: runtime) else {
                throw failure("Python runtime unavailable. Run just install, then rebuild menu app.")
            }
            let helper = Process()
            helper.executableURL = URL(fileURLWithPath: runtime)
            helper.arguments = ["-u", "-m", "webcam_mods.control"]
            let stdin = Pipe(), stdout = Pipe(), stderr = Pipe()
            helper.standardInput = stdin
            helper.standardOutput = stdout
            helper.standardError = stderr
            stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                Task { @MainActor in
                    guard let self, self.workerGeneration == generation else { return }
                    self.consume(bytes)
                }
            }
            stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                Task { @MainActor in
                    guard let self, self.workerGeneration == generation else { return }
                    self.diagnosticBuffer.append(bytes)
                    if self.diagnosticBuffer.count > 8192 { self.diagnosticBuffer.removeFirst(self.diagnosticBuffer.count - 8192) }
                }
            }
            helper.terminationHandler = { [weak self] helper in
                Task { @MainActor in
                    guard let self, self.workerGeneration == generation else { return }
                    self.connected = false
                    self.input = nil
                    self.process = nil
                    self.outputBuffer.removeAll()
                    let callbacks = self.pending.values
                    self.pending.removeAll()
                    for callback in callbacks { callback(.failure(self.failure("Worker exited. Reconnect worker; run just install if this repeats."))) }
                    if self.quitting { NSApp.reply(toApplicationShouldTerminate: true); NSApp.terminate(nil) }
                    else if helper.terminationStatus != 0 {
                        self.state = "error"
                        self.error = self.error ?? "Worker exited (\(helper.terminationStatus)). Run just install, then reopen app."
                    } else { self.state = "idle" }
                }
            }
            try helper.run()
            process = helper
            input = stdin.fileHandleForWriting
            request("hello") { [weak self] result in
                guard let self else { return }
                switch result {
                case .success(let value):
                    guard let hello = value as? [String: Any], hello["protocol"] as? Int == 1 else {
                        self.error = "Worker protocol mismatch. Reinstall CLI and rebuild app."
                        self.state = "error"
                        self.process?.terminate()
                        return
                    }
                    self.backendVersion = hello["version"] as? String ?? "unknown"
                    self.connected = true
                    self.refresh()
                case .failure(let issue):
                    self.error = issue.localizedDescription
                    self.state = "error"
                    self.process?.terminate()
                }
            }
        } catch { self.error = error.localizedDescription; state = "error" }
    }

    private func failure(_ message: String) -> NSError { NSError(domain: "WebcamMods", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }

    private func consume(_ bytes: Data) {
        guard !bytes.isEmpty else { return }
        outputBuffer.append(bytes)
        guard outputBuffer.count < 1_048_576 else {
            outputBuffer.removeAll()
            error = "Worker response exceeded limit. Restart app."
            return
        }
        while let newline = outputBuffer.firstIndex(of: 10) {
            let line = outputBuffer[..<newline]
            outputBuffer.removeSubrange(...newline)
            guard let message = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else {
                error = "Invalid worker response. Reinstall CLI and restart app."
                continue
            }
            if message["event"] as? String == "status", let data = message["data"] as? [String: Any] {
                state = data["state"] as? String ?? "idle"
                error = data["error"] as? String
            } else if let id = message["id"] as? Int, let callback = pending.removeValue(forKey: id) {
                if let message = message["error"] as? String { callback(.failure(failure(message))) }
                else { callback(.success(message["result"] ?? NSNull())) }
            }
        }
    }

    private func request(_ method: String, params: [String: Any] = [:], completion: @escaping (Result<Any, Error>) -> Void = { _ in }) {
        guard let input else { completion(.failure(failure("Worker unavailable. Reopen app."))); return }
        nextID += 1
        let id = nextID
        do {
            var data = try JSONSerialization.data(withJSONObject: ["id": id, "method": method, "params": params])
            data.append(10)
            pending[id] = completion
            try input.write(contentsOf: data)
            DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
                self?.expireRequest(id)
            }
        } catch { pending.removeValue(forKey: id); completion(.failure(error)) }
    }

    private func expireRequest(_ id: Int) {
        guard let callback = pending.removeValue(forKey: id) else { return }
        callback(.failure(failure("Worker did not respond. Restart app; check installed CLI if this repeats.")))
    }

    static func selfTest() throws {
        func check(_ condition: Bool, _ message: String) throws {
            guard condition else { throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        let model = SessionModel()
        let pipe = Pipe()
        model.input = pipe.fileHandleForWriting
        var result: Any?
        var requestError: Error?
        model.request("status") { response in
            switch response {
            case .success(let value): result = value
            case .failure(let issue): requestError = issue
            }
        }
        let bytes = pipe.fileHandleForReading.availableData
        let request = try JSONSerialization.jsonObject(with: bytes) as? [String: Any]
        try check(request?["method"] as? String == "status", "Request method serialization")
        try check(request?["id"] as? Int == 1, "Request identifier serialization")
        model.consume(Data("{\"id\":1,\"result\":{\"state\":\"idle\"}}".utf8))
        try check(result == nil, "Partial response must wait for newline")
        model.consume(Data("\n{\"event\":\"status\",\"data\":{\"state\":\"running\"}}\n".utf8))
        try check((result as? [String: Any])?["state"] as? String == "idle", "Response routing")
        try check(model.state == "running", "Status event routing")
        model.request("stop") { if case .failure(let issue) = $0 { requestError = issue } }
        model.consume(Data("{\"id\":2,\"error\":\"capture failed\"}\n".utf8))
        try check(requestError?.localizedDescription == "capture failed", "Structured worker error")
        requestError = nil
        model.request("status") { if case .failure(let issue) = $0 { requestError = issue } }
        model.expireRequest(3)
        try check(requestError != nil && model.pending.isEmpty, "Request timeout clears callback")
        model.consume(Data("invalid json\n".utf8))
        try check(model.error?.contains("Invalid worker response") == true, "Malformed response recovery")
        model.consume(Data("{\"event\":\"status\",\"data\":{\"state\":\"idle\"}}\n".utf8))
        try check(model.error == nil && model.state == "idle", "Status recovery clears previous error")
        model.stop()
        model.consume(Data("{\"id\":4,\"result\":{\"state\":\"idle\"}}\n".utf8))
        try check(model.state == "idle", "Stop response restores idle without a status event")
        var configuration = Configuration()
        configuration.fps = 29.97
        let profileBytes = try JSONSerialization.data(withJSONObject: [["name": "Example", "config": configuration.json]])
        let profiles = try JSONDecoder().decode([Profile].self, from: profileBytes)
        try check(profiles[0].config.width == 640 && profiles[0].config.effect == "plain" && profiles[0].config.fps == 29.97, "Profile configuration decoding")
        model.profiles = profiles
        model.selectProfile("Example")
        try check(model.selectedProfile == "Example" && model.profileName == "Example", "Profile selection")
        let cameraBytes = Data("[{\"index\":2,\"name\":\"External Camera\",\"id\":\"stable-camera\"}]".utf8)
        let cameras = try JSONDecoder().decode([Camera].self, from: cameraBytes)
        try check(cameras[0].id == "stable-camera", "Camera identity decoding")
        model.cameras = cameras
        model.inventoryCapture = model.config.capture
        model.selectCamera("stable-camera")
        try check(model.config.camera_id == "stable-camera" && model.config.input_device == 2, "Camera selection preserves identity")
        model.config.input_device = 0
        model.reconcileCamera()
        try check(model.config.input_device == 2 && !model.cameraUnavailable, "Camera enumeration changes resolve by identity")
        model.config.camera_id = "removed-camera"
        try check(model.cameraUnavailable, "Removed camera must not select another device")
        var outputConfig = Configuration()
        outputConfig.output_width = 1280
        outputConfig.output_height = 720
        outputConfig.output_fps = 24
        let outputDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(outputConfig))
        try check(outputDecoded.output_width == 1280 && outputDecoded.output_fps == 24, "Independent output settings round trip")
        try check(profiles[0].config.camera_id == nil && profiles[0].config.output_width == nil, "Legacy profile optional fields")
        model.config = profiles[0].config
        try check(!model.profileModified, "Selected saved profile begins clean")
        model.config.brightness = 20
        try check(model.profileModified && model.selectedProfile == "Example", "Draft changes mark selected profile modified without writing")
        model.config.brightness = 0
        try check(!model.profileModified, "Restoring saved settings clears modified state")
        model.inventoryGeneration = 2
        model.inventoryPending = true
        model.config.capture = "opencv"
        model.acceptInventory(.success([["index": 2, "name": "Stale", "id": "old"]]), generation: 1, capture: "avfoundation")
        try check(model.inventoryPending, "Old inventory response cannot unlock Start")
        model.acceptInventory(.success([["index": 2, "name": "Older same backend", "id": "old"]]), generation: 1, capture: "opencv")
        try check(model.inventoryPending, "Out-of-order same-backend response ignored")
        model.connected = true
        model.start()
        try check(model.state == "idle", "Start blocked while inventory pending before camera permission")
        model.connected = false
        model.acceptInventory(.success([["index": 3, "name": "Current", "id": "new"]]), generation: 2, capture: "opencv")
        try check(!model.inventoryPending && model.cameras[0].id == "new", "Current inventory response accepted")
        model.config.capture = "avfoundation"
        try check(model.cameraUnavailable, "Backend changes invalidate inventory immediately")
        let issueBytes = Data("[{\"name\":\"Broken profile\",\"error\":\"invalid configuration\"}]".utf8)
        let issues = try JSONDecoder().decode([ProfileIssue].self, from: issueBytes)
        try check(issues[0].name == "Broken profile", "Structured profile warning decoding")
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2, bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        bitmap.bitmapData?.initialize(repeating: 127, count: bitmap.bytesPerRow * bitmap.pixelsHigh)
        let jpeg = bitmap.representation(using: .jpeg, properties: [:])!.base64EncodedString()
        let frame: [String: Any] = ["jpeg": jpeg, "width": 2, "height": 2]
        model.acceptPreview(.success(frame))
        try check(model.previewImage != nil && model.previewError == nil, "Bounded JPEG preview decoding")
        model.state = "idle"
        try check(model.previewImage == nil, "Stopping clears preview")
        model.error = nil
        model.acceptPreview(.success(["jpeg": "invalid", "width": 2, "height": 2]))
        try check(model.previewError != nil && model.error == nil, "Preview errors remain separate from session errors")
        model.state = "running"
        model.connected = true
        let previewID = model.nextID + 1
        model.pollPreview(visible: true)
        model.pollPreview(visible: true)
        try check(model.nextID == previewID && model.previewPending, "Only one preview request in flight")
        model.pollPreview(visible: false)
        let reply = try JSONSerialization.data(withJSONObject: ["id": previewID, "result": frame])
        model.consume(reply + Data([10]))
        try check(model.previewImage == nil && !model.previewPending, "Hidden window rejects late preview")
        model.pollPreview(visible: true)
        let oldID = model.nextID
        model.state = "stopping"
        model.state = "running"
        let oldReply = try JSONSerialization.data(withJSONObject: ["id": oldID, "result": frame])
        model.consume(oldReply + Data([10]))
        try check(model.previewImage == nil, "New session rejects old preview")
        model.pollPreview(visible: true)
        model.expireRequest(model.nextID)
        try check(!model.previewPending && model.previewError != nil, "Preview timeout releases in-flight request")
        model.state = "idle"
        model.pollPreview(visible: true)
        try check(!model.previewPending, "Idle window does not poll frames")
        try pipe.fileHandleForWriting.close()
        try pipe.fileHandleForReading.close()
        try helperSelfTest()
        print("Native model self-test passed (JSONL, errors, timeout, profiles, camera identity, preview lifecycle).")
    }

    private static func helperSelfTest() throws {
        guard let runtimeURL = Bundle.main.url(forResource: "backend-python", withExtension: "txt") else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1)
        }
        let runtime = try String(contentsOf: runtimeURL, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let helper = Process()
        helper.executableURL = URL(fileURLWithPath: runtime)
        helper.arguments = ["-u", "-m", "webcam_mods.control"]
        var environment = ProcessInfo.processInfo.environment
        environment["XDG_CONFIG_HOME"] = directory.path
        helper.environment = environment
        let input = Pipe(), output = Pipe()
        helper.standardInput = input
        helper.standardOutput = output
        helper.standardError = FileHandle.nullDevice
        let ended = DispatchSemaphore(value: 0)
        helper.terminationHandler = { _ in ended.signal() }
        try helper.run()
        let requests: [[String: Any]] = [
            ["id": 1, "method": "hello"],
            ["id": 2, "method": "profiles.save", "params": ["name": "Native test", "config": Configuration().json]],
            ["id": 3, "method": "profiles.list"],
            ["id": 4, "method": "preview.get", "params": [:]],
            ["id": 5, "method": "shutdown"]
        ]
        for request in requests {
            var bytes = try JSONSerialization.data(withJSONObject: request)
            bytes.append(10)
            try input.fileHandleForWriting.write(contentsOf: bytes)
        }
        try input.fileHandleForWriting.close()
        guard ended.wait(timeout: .now() + 10) == .success else {
            if helper.isRunning { kill(helper.processIdentifier, SIGKILL) }
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper timed out"])
        }
        let lines = output.fileHandleForReading.readDataToEndOfFile().split(separator: 10)
        guard helper.terminationStatus == 0, lines.count == 5 else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper failed"])
        }
        let messages = try lines.map { try JSONSerialization.jsonObject(with: Data($0)) as? [String: Any] }
        guard let hello = messages[0]?["result"] as? [String: Any], hello["protocol"] as? Int == 1,
              let profiles = messages[2]?["result"] as? [[String: Any]],
              messages[3]?["result"] is NSNull else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper response mismatch"])
        }
        let profileData = try JSONSerialization.data(withJSONObject: profiles)
        let decoded = try JSONDecoder().decode([Profile].self, from: profileData)
        guard decoded.count == 1, decoded[0].config.brightness == 0, decoded[0].config.capture == "avfoundation" else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper profile mismatch"])
        }
    }

    func refresh() {
        refreshCameras()
        request("profiles.list") { [weak self] result in
            self?.decode(result, as: [Profile].self) { self?.profiles = $0 }
        }
        request("profiles.errors") { [weak self] result in
            self?.decode(result, as: [ProfileIssue].self) { issues in
                self?.profileWarning = issues.isEmpty ? nil : "Some saved profiles could not load. \(issues.map { "\($0.name): \($0.error)" }.joined(separator: "; ")). Use profile-save or profile-delete for these names, then Refresh."
            }
        }
    }

    func refreshCameras() {
        inventoryGeneration += 1
        let generation = inventoryGeneration
        let capture = config.capture
        inventoryPending = true
        cameras = []
        inventoryCapture = nil
        request("cameras.list", params: ["capture": capture]) { [weak self] result in
            self?.acceptInventory(result, generation: generation, capture: capture)
        }
    }

    private func acceptInventory(_ result: Result<Any, Error>, generation: Int, capture: String) {
        guard generation == inventoryGeneration, capture == config.capture else { return }
        inventoryPending = false
        decode(result, as: [Camera].self) {
            cameras = $0
            inventoryCapture = capture
            reconcileCamera()
        }
    }

    private func decode<T: Decodable>(_ result: Result<Any, Error>, as type: T.Type, apply: (T) -> Void) {
        do {
            let value = try result.get()
            let data = try JSONSerialization.data(withJSONObject: value)
            apply(try JSONDecoder().decode(type, from: data))
        } catch { self.error = error.localizedDescription }
    }

    func selectProfile(_ name: String) {
        selectedProfile = name
        guard let profile = profiles.first(where: { $0.name == name }) else { return }
        config = profile.config
        profileName = name
        reconcileCamera()
        if connected { refreshCameras() }
    }

    func saveProfile() {
        let name = profileName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { error = "Enter a profile name before saving."; return }
        reconcileCamera()
        request("profiles.save", params: ["name": name, "config": config.json]) { [weak self] result in
            switch result {
            case .success: self?.selectedProfile = name; self?.refresh()
            case .failure(let issue): self?.error = issue.localizedDescription
            }
        }
    }

    func deleteProfile() {
        request("profiles.delete", params: ["name": selectedProfile]) { [weak self] result in
            switch result {
            case .success: self?.selectedProfile = ""; self?.profileName = ""; self?.refresh()
            case .failure(let issue): self?.error = issue.localizedDescription
            }
        }
    }

    func start() {
        guard !active, connected else { return }
        guard !cameraUnavailable else { error = "Saved camera unavailable. Reconnect it or choose another camera."; return }
        error = nil
        state = "starting"
        startGeneration += 1
        let generation = startGeneration
        AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
            Task { @MainActor in
                guard let self else { return }
                guard self.startGeneration == generation, self.state == "starting", self.connected else { return }
                guard granted else {
                    self.state = "idle"
                    self.error = "Camera access denied. Enable Webcam Mods in System Settings > Privacy & Security > Camera."
                    return
                }
                self.request("start", params: ["config": self.config.json, "output": self.outputMode]) { [weak self] result in
                    if case .failure(let issue) = result {
                        self?.state = "error"
                        self?.error = issue.localizedDescription
                    }
                }
            }
        }
    }

    func stop() {
        startGeneration += 1
        state = "stopping"
        request("stop") { [weak self] result in
            switch result {
            case .success(let value):
                if let status = value as? [String: Any] {
                    self?.state = status["state"] as? String ?? "idle"
                    self?.error = status["error"] as? String
                }
            case .failure(let issue):
                self?.state = "error"
                self?.error = issue.localizedDescription
            }
        }
    }

    func chooseImage() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK { config.image_path = panel.url?.path ?? "" }
    }

    func quit() {
        guard !quitting else { return }
        quitting = true
        startGeneration += 1
        guard let process else { NSApp.terminate(nil); return }
        request("shutdown")
        // A blocked native call cannot keep an invisible camera worker alive indefinitely.
        DispatchQueue.main.asyncAfter(deadline: .now() + 12) {
            if process.isRunning { process.terminate() }
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                NSApp.reply(toApplicationShouldTerminate: true)
                NSApp.terminate(nil)
            }
        }
    }
}

struct ControlPanel: View {
    @ObservedObject var model: SessionModel
    @State private var advanced = false
    @State private var confirmDelete = false
    @State private var showError = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Webcam Mods", systemImage: "camera.aperture").font(.headline)
                Spacer()
                Text(model.state.capitalized).font(.caption).foregroundStyle(model.state == "running" ? .green : .secondary)
            }
            if let error = model.error {
                HStack(alignment: .top) {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.red).lineLimit(3)
                    Button("Details") { showError = true }
                }
            }
            if let warning = model.profileWarning {
                Label(warning, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange).lineLimit(4).help(warning)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("Output", selection: $model.outputMode) {
                        Text("Preview only").tag("preview")
                        Text("OBS Virtual Camera").tag("virtualcam")
                    }
                    Text(model.outputMode == "preview" ? "Test camera and effects in this window." : "Send video to OBS Virtual Camera and preview here.")
                        .font(.caption).foregroundStyle(.secondary)
                    Picker("Camera", selection: Binding(get: { model.selectedCameraID }, set: model.selectCamera)) {
                        if model.cameraUnavailable { Text(model.cameras.isEmpty ? "No cameras found" : "Saved camera unavailable").tag(model.selectedCameraID) }
                        ForEach(model.cameras) { camera in Text(camera.name).tag(camera.id) }
                    }.disabled(model.inventoryPending)
                    if model.cameraUnavailable {
                        Text(model.inventoryPending ? "Refreshing camera inventory..." : "Reconnect saved camera or choose another camera.").font(.caption).foregroundStyle(.secondary)
                    }
                    HStack {
                        Picker("Profile", selection: Binding(get: { model.selectedProfile }, set: model.selectProfile)) {
                            Text("Custom").tag("")
                            ForEach(model.profiles) { profile in
                                Text(profile.name + (profile.name == model.selectedProfile && model.profileModified ? " (modified)" : "")).tag(profile.name)
                            }
                        }
                        Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }.help("Refresh cameras and profiles")
                    }
                    HStack {
                        TextField("Profile name", text: $model.profileName)
                        Button("Save", action: model.saveProfile)
                        Button { confirmDelete = true } label: { Image(systemName: "trash") }.disabled(model.selectedProfile.isEmpty).help("Delete selected profile")
                    }
                    Divider()
                    Picker("Background", selection: $model.config.effect) {
                        Text("Original").tag("plain")
                        Text("Blur").tag("blur")
                        Text("Solid gray").tag("color")
                        Text("Image").tag("image")
                        Text("Face tracking").tag("track")
                    }
                    if model.config.effect == "blur" {
                        Stepper("Blur: \(model.config.blur_kernel)", value: $model.config.blur_kernel, in: 1...151, step: 2)
                    }
                    if model.config.effect == "color" {
                        slider("Gray", value: $model.config.color, range: 0...255)
                    }
                    if model.config.effect == "image" {
                        HStack {
                            Text(model.config.image_path.isEmpty ? "Choose background image" : URL(fileURLWithPath: model.config.image_path).lastPathComponent).lineLimit(1).truncationMode(.middle)
                            Spacer()
                            Button("Choose...", action: model.chooseImage)
                        }
                    }
                    Toggle("Track face", isOn: $model.config.track).disabled(model.config.effect == "track")
                    slider("Brightness", value: $model.config.brightness, range: 0...255)
                    DisclosureGroup("Advanced", isExpanded: $advanced) {
                        VStack(spacing: 9) {
                            HStack {
                                Text("Capture size")
                                TextField("Width", value: $model.config.width, format: .number)
                                Text("x")
                                TextField("Height", value: $model.config.height, format: .number)
                            }
                            Stepper("Capture FPS: \(model.config.fps.formatted(.number.precision(.fractionLength(0...2))))", value: $model.config.fps, in: 1...60)
                            Toggle("Use capture settings for output", isOn: Binding(
                                get: { model.config.output_width == nil && model.config.output_height == nil && model.config.output_fps == nil },
                                set: { inherited in
                                    model.config.output_width = inherited ? nil : model.config.width
                                    model.config.output_height = inherited ? nil : model.config.height
                                    model.config.output_fps = inherited ? nil : model.config.fps
                                }))
                            if model.config.output_width != nil || model.config.output_height != nil || model.config.output_fps != nil {
                                HStack {
                                    Text("Output size")
                                    TextField("Width", value: Binding(get: { model.config.output_width ?? model.config.width }, set: { model.config.output_width = $0 }), format: .number)
                                    Text("x")
                                    TextField("Height", value: Binding(get: { model.config.output_height ?? model.config.height }, set: { model.config.output_height = $0 }), format: .number)
                                }
                                Stepper("Output FPS: \((model.config.output_fps ?? model.config.fps).formatted(.number.precision(.fractionLength(0...2))))", value: Binding(get: { model.config.output_fps ?? model.config.fps }, set: { model.config.output_fps = $0 }), in: 1...60)
                            }
                            Stepper("Processing FPS: \(model.config.processing_fps.formatted(.number.precision(.fractionLength(0...2))))", value: $model.config.processing_fps, in: 1...60)
                            Picker("Segmentation", selection: $model.config.segmentation) {
                                Text("MediaPipe").tag("mediapipe"); Text("Apple Vision").tag("vision")
                            }
                            Picker("Processing", selection: $model.config.processing) {
                                Text("OpenCV").tag("opencv"); Text("Core Image").tag("coreimage")
                            }
                            Picker("Capture", selection: $model.config.capture) {
                                Text("Automatic").tag("auto"); Text("OpenCV").tag("opencv"); Text("AVFoundation").tag("avfoundation")
                            }
                            Toggle("Repeat latest frame", isOn: $model.config.repeat_frames)
                            Toggle("Smooth segmentation mask", isOn: $model.config.smoothing)
                        }.padding(.top, 6)
                    }
                }.disabled(model.active || !model.connected)
            }.frame(maxHeight: .infinity)
            Text(model.active ? "Stop camera to change settings." : "Choose settings, then start camera to preview.")
                .font(.caption).foregroundStyle(.secondary)
            if !model.connected && !model.hasWorker {
                Button("Reconnect worker", action: model.reconnect)
            }
            HStack {
                Button(model.active ? "Stop camera" : "Start camera", action: model.active ? model.stop : model.start)
                    .buttonStyle(.borderedProminent).disabled(!model.connected || model.state == "stopping" || (!model.active && model.cameraUnavailable))
                Spacer()
                Button("Quit", action: model.quit)
            }
            HStack {
                Text(model.build).help("Built \(model.buildDate)")
                Spacer()
                Text(model.backendVersion.isEmpty ? "Worker disconnected" : "Backend \(model.backendVersion)")
            }.font(.caption2).foregroundStyle(.secondary)
        }.padding(18).frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { model.connect() }
        .onChange(of: model.config.capture) { _ in
            if model.connected && !model.active { model.refreshCameras() }
        }
        .alert("Delete profile?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive, action: model.deleteProfile)
            Button("Cancel", role: .cancel) {}
        } message: { Text("Delete \(model.selectedProfile)? Current camera settings remain available.") }
        .sheet(isPresented: $showError) {
            VStack(alignment: .leading, spacing: 14) {
                Text("Camera error").font(.headline)
                ScrollView {
                    Text(model.error ?? "Error cleared.")
                        .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                }
                Button("Done") { showError = false }
            }.padding(18).frame(width: 480, height: 360)
        }
    }

    private func slider(_ title: String, value: Binding<Int>, range: ClosedRange<Double>) -> some View {
        HStack {
            Text(title).frame(width: 75, alignment: .leading)
            Slider(value: Binding(get: { Double(value.wrappedValue) }, set: { value.wrappedValue = Int($0) }), in: range, step: 1)
            Text("\(value.wrappedValue)").monospacedDigit().frame(width: 32, alignment: .trailing)
        }
    }
}

struct PreviewPanel: View {
    @ObservedObject var model: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Video preview").font(.headline)
                Spacer()
                Text(model.outputMode == "preview" ? "Preview only" : "OBS Virtual Camera")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ZStack {
                Color.black
                if let image = model.previewImage {
                    Image(nsImage: image).resizable().scaledToFit()
                } else {
                    VStack(spacing: 12) {
                        Image(systemName: "video").font(.system(size: 36))
                        Text(model.state == "starting" ? "Starting camera..." : model.state == "running" ? "Waiting for video..." : "Camera stopped")
                            .font(.headline)
                        Text("Start camera to see your processed video.").font(.caption)
                    }.foregroundStyle(.white.opacity(0.7))
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .accessibilityLabel("Processed video preview")
            if let error = model.previewError {
                Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
            }
            Text("Preview shows final framing and effects. Preview refreshes up to 10 FPS; output uses configured FPS.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct MainWindow: View {
    @ObservedObject var model: SessionModel
    var body: some View {
        GeometryReader { geometry in
            if geometry.size.width >= 820 {
                HStack(spacing: 0) {
                    PreviewPanel(model: model).frame(maxWidth: .infinity)
                    Divider()
                    ControlPanel(model: model).frame(width: 370)
                }
            } else {
                VStack(spacing: 0) {
                    PreviewPanel(model: model).frame(height: min(280, geometry.size.height * 0.38))
                    Divider()
                    ControlPanel(model: model)
                }
            }
        }
    }
}

@main
struct WebcamModsApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = SessionModel()
    init() {
        if CommandLine.arguments.contains("--self-test") {
            do { try SessionModel.selfTest(); exit(0) }
            catch {
                FileHandle.standardError.write(Data("Native model self-test failed: \(error.localizedDescription)\n".utf8))
                exit(1)
            }
        }
    }
    var body: some Scene {
        MenuBarExtra("Webcam Mods", systemImage: model.state == "running" ? "video.fill" : "video") {
            Text("Camera: \(model.state.capitalized)")
            Button(model.active ? "Stop camera" : "Start camera", action: model.active ? model.stop : model.start)
                .disabled(!model.connected || model.state == "stopping" || (!model.active && model.cameraUnavailable))
            Button("Open window") { delegate.showControls() }.keyboardShortcut("o")
            Divider()
            Button("Quit Webcam Mods", action: model.quit).keyboardShortcut("q")
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var controlsWindow: NSWindow?
    private var previewTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        showControls()
        previewTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                let visible = self.controlsWindow.map { $0.isVisible && !$0.isMiniaturized } ?? false
                SessionModel.current?.pollPreview(visible: visible)
            }
        }
    }

    func showControls() {
        guard let model = SessionModel.current else { return }
        if controlsWindow == nil {
            let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 700), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window.title = "Webcam Mods"
            window.contentView = NSHostingView(rootView: MainWindow(model: model))
            window.minSize = NSSize(width: 420, height: 650)
            window.isReleasedWhenClosed = false
            window.setFrameAutosaveName("WebcamModsMain")
            window.center()
            controlsWindow = window
        }
        controlsWindow?.deminiaturize(nil)
        controlsWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showControls()
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model = SessionModel.current, model.hasWorker else { return .terminateNow }
        model.quit()
        return .terminateLater
    }
}
