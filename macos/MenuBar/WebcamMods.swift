import SwiftUI
import AVFoundation
import AppKit

struct Camera: Decodable, Identifiable {
    let index: Int
    let name: String
    var id: Int { index }
}

struct Configuration: Codable {
    var input_device = 0
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
    @Published var state = "idle"
    @Published var error: String?
    @Published var connected = false
    private var process: Process?
    private var input: FileHandle?
    private var nextID = 0
    private var pending: [Int: (Result<Any, Error>) -> Void] = [:]
    private var outputBuffer = Data()
    private var diagnosticBuffer = Data()
    private var quitting = false
    private var startGeneration = 0

    init() { Self.current = self }
    var hasWorker: Bool { process != nil }

    var active: Bool { ["starting", "running", "stopping"].contains(state) }
    var build: String {
        let info = Bundle.main.infoDictionary ?? [:]
        return "\(info["CFBundleShortVersionString"] as? String ?? "unknown") (\(info["BuildCommit"] as? String ?? "unknown"))"
    }
    var buildDate: String { Bundle.main.object(forInfoDictionaryKey: "BuildDate") as? String ?? "unknown" }

    func connect() {
        guard process == nil else { return }
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
                Task { @MainActor in self?.consume(bytes) }
            }
            stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                Task { @MainActor in
                    guard let self else { return }
                    self.diagnosticBuffer.append(bytes)
                    if self.diagnosticBuffer.count > 8192 { self.diagnosticBuffer.removeFirst(self.diagnosticBuffer.count - 8192) }
                }
            }
            helper.terminationHandler = { [weak self] helper in
                Task { @MainActor in
                    guard let self else { return }
                    self.connected = false
                    self.input = nil
                    self.process = nil
                    let callbacks = self.pending.values
                    self.pending.removeAll()
                    for callback in callbacks { callback(.failure(self.failure("Worker exited. Check Python installation and restart app."))) }
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
        let cameraBytes = Data("[{\"index\":2,\"name\":\"External Camera\"}]".utf8)
        let cameras = try JSONDecoder().decode([Camera].self, from: cameraBytes)
        try check(cameras[0].id == 2, "Camera identity decoding")
        try pipe.fileHandleForWriting.close()
        try pipe.fileHandleForReading.close()
        try helperSelfTest()
        print("Native model self-test passed (JSONL, errors, timeout, profiles, camera identity).")
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
            ["id": 4, "method": "shutdown"]
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
        guard helper.terminationStatus == 0, lines.count == 4 else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper failed"])
        }
        let messages = try lines.map { try JSONSerialization.jsonObject(with: Data($0)) as? [String: Any] }
        guard let hello = messages[0]?["result"] as? [String: Any], hello["protocol"] as? Int == 1,
              let profiles = messages[2]?["result"] as? [[String: Any]] else {
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
    }

    func refreshCameras() {
        request("cameras.list", params: ["capture": config.capture]) { [weak self] result in
            self?.decode(result, as: [Camera].self) { self?.cameras = $0 }
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
    }

    func saveProfile() {
        let name = profileName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { error = "Enter a profile name before saving."; return }
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
                self.request("start", params: ["config": self.config.json]) { [weak self] result in
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

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Webcam Mods", systemImage: "camera.aperture").font(.headline)
                Spacer()
                Text(model.state.capitalized).font(.caption).foregroundStyle(model.state == "running" ? .green : .secondary)
            }
            if let error = model.error {
                Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
            Group {
                Picker("Camera", selection: $model.config.input_device) {
                    if model.cameras.isEmpty { Text("No cameras found").tag(model.config.input_device) }
                    ForEach(model.cameras) { camera in Text(camera.name).tag(camera.index) }
                }
                HStack {
                    Picker("Profile", selection: Binding(get: { model.selectedProfile }, set: model.selectProfile)) {
                        Text("Custom").tag("")
                        ForEach(model.profiles) { Text($0.name).tag($0.name) }
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
                            Text("Size")
                            TextField("Width", value: $model.config.width, format: .number)
                            Text("x")
                            TextField("Height", value: $model.config.height, format: .number)
                        }
                        Stepper("Capture / output FPS: \(model.config.fps.formatted(.number.precision(.fractionLength(0...2))))", value: $model.config.fps, in: 1...60)
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
            HStack {
                Button(model.active ? "Stop camera" : "Start camera", action: model.active ? model.stop : model.start)
                    .buttonStyle(.borderedProminent).disabled(!model.connected || model.state == "stopping")
                Spacer()
                Button("Quit", action: model.quit)
            }
            HStack {
                Text(model.build).help("Built \(model.buildDate)")
                Spacer()
                Text("Local camera controls")
            }.font(.caption2).foregroundStyle(.secondary)
        }.padding(18).frame(width: 370)
        .onAppear { model.connect() }
        .onChange(of: model.config.capture) { _ in
            if model.connected && !model.active { model.refreshCameras() }
        }
        .alert("Delete profile?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive, action: model.deleteProfile)
            Button("Cancel", role: .cancel) {}
        } message: { Text("Delete \(model.selectedProfile)? Current camera settings remain available.") }
    }

    private func slider(_ title: String, value: Binding<Int>, range: ClosedRange<Double>) -> some View {
        HStack {
            Text(title).frame(width: 75, alignment: .leading)
            Slider(value: Binding(get: { Double(value.wrappedValue) }, set: { value.wrappedValue = Int($0) }), in: range, step: 1)
            Text("\(value.wrappedValue)").monospacedDigit().frame(width: 32, alignment: .trailing)
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
            ControlPanel(model: model)
        }.menuBarExtraStyle(.window)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let model = SessionModel.current, model.hasWorker else { return .terminateNow }
        model.quit()
        return .terminateLater
    }
}
