import SwiftUI
import AVFoundation
import AppKit
import Carbon.HIToolbox
import UniformTypeIdentifiers

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
    // solid background as #RRGGBB; nil uses the gray level above
    var background_color: String?
    var image_path = ""
    var image_blur = false
    // point of the background image kept in view when it fills a different shape
    var image_x = 0.5
    var image_y = 0.5
    var spotlight_dim = 60
    var spotlight_lift = 20
    var track = false
    var segmentation = "mediapipe"
    var processing = "opencv"
    var capture = "avfoundation"
    var repeat_frames = true
    var processing_fps = 30.0
    var smoothing = false
    var signal_pattern = "color-bars"
    var mirror = false
    var flip_vertical = false
    // clockwise degrees; quarter turns swap the default output size
    var rotate = 0
    // [x, y, width, height] fractions of the oriented camera frame; nil shows it all
    var crop: [Double]?
    var track_face_height = 0.4
    var track_target_y = 0.42
    var track_max_zoom = 2.0
    var track_follow_seconds = 0.25
    var track_deadzone = 0.08
    // color after background and brightness; exposure in stops, 0 leaves the picture as is
    var exposure = 0.0
    var contrast = 0
    var saturation = 0
    var temperature = 0
    var tint = 0
    var sharpness = 0
    // lifts dark pictures gradually, 0 off
    var auto_light = 0
    // final grade: none, a built-in look, or custom with a .cube file
    var look = "none"
    var look_path = ""
    var look_strength = 100

    var tracking: Bool { track || effect == "track" }

    var colorAdjusted: Bool {
        exposure != 0 || contrast != 0 || saturation != 0 || temperature != 0 || tint != 0 || sharpness != 0 || auto_light != 0
    }

    mutating func resetColor() {
        let defaults = Configuration()
        exposure = defaults.exposure
        contrast = defaults.contrast
        saturation = defaults.saturation
        temperature = defaults.temperature
        tint = defaults.tint
        sharpness = defaults.sharpness
        auto_light = defaults.auto_light
    }

    var backgroundColor: NSColor {
        let hex = background_color ?? String(format: "#%02X%02X%02X", color, color, color)
        let value = Int(hex.dropFirst(), radix: 16) ?? 0
        return NSColor(srgbRed: CGFloat(value >> 16 & 255) / 255, green: CGFloat(value >> 8 & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
    }

    mutating func setBackgroundColor(_ picked: NSColor) {
        guard let rgb = picked.usingColorSpace(.sRGB) else { return }
        func byte(_ component: CGFloat) -> Int { Int((min(max(component, 0), 1) * 255).rounded()) }
        background_color = String(format: "#%02X%02X%02X", byte(rgb.redComponent), byte(rgb.greenComponent), byte(rgb.blueComponent))
    }

    mutating func resetFramingPreferences() {
        let defaults = Configuration()
        track_face_height = defaults.track_face_height
        track_target_y = defaults.track_target_y
        track_max_zoom = defaults.track_max_zoom
        track_follow_seconds = defaults.track_follow_seconds
        track_deadzone = defaults.track_deadzone
    }

    var json: [String: Any] {
        (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(self))) as? [String: Any] ?? [:]
    }

    // capture and output shape; keep in step with RESTART_FIELDS in profiles.py
    func withRestartFields(from other: Configuration) -> Configuration {
        var copy = self
        copy.input_device = other.input_device
        copy.camera_id = other.camera_id
        copy.width = other.width
        copy.height = other.height
        copy.fps = other.fps
        copy.capture = other.capture
        copy.output_width = other.output_width
        copy.output_height = other.output_height
        copy.output_fps = other.output_fps
        copy.repeat_frames = other.repeat_frames
        copy.processing_fps = other.processing_fps
        copy.signal_pattern = other.signal_pattern
        copy.rotate = other.rotate
        return copy
    }

    func needsRestart(from running: Configuration) -> Bool {
        var current = self
        var original = running
        // enumeration-only index changes keep the same physical camera
        if current.camera_id != nil && current.camera_id == original.camera_id {
            current.input_device = 0
            original.input_device = 0
        }
        return current.withRestartFields(from: original) != current
    }
}

struct SessionStats: Equatable {
    var processedFPS: Double?
    var sentFPS: Double?
    var effectMS: Double?

    var summary: String {
        func value(_ number: Double?, _ unit: String) -> String {
            number.map { "\($0.formatted(.number.precision(.fractionLength(0...1)))) \(unit)" } ?? "--"
        }
        return "Processed \(value(processedFPS, "fps")), sent \(value(sentFPS, "fps")), effects \(value(effectMS, "ms"))"
    }
}

struct OutputShape: Identifiable {
    let id: String
    let label: String
    let aspect: Double

    static let presets = [
        OutputShape(id: "16:9", label: "Wide 16:9", aspect: 16 / 9),
        OutputShape(id: "4:3", label: "Standard 4:3", aspect: 4 / 3),
        OutputShape(id: "1:1", label: "Square 1:1", aspect: 1),
        OutputShape(id: "9:16", label: "Portrait 9:16", aspect: 9 / 16),
    ]
}

extension Configuration {
    // capture size after rotation; output defaults to it
    var orientedWidth: Int { rotate == 90 || rotate == 270 ? height : width }
    var orientedHeight: Int { rotate == 90 || rotate == 270 ? width : height }

    // "camera" while output follows capture, a preset id, or "custom"
    var outputShape: String {
        guard output_width != nil || output_height != nil else { return "camera" }
        let aspect = Double(output_width ?? orientedWidth) / Double(max(output_height ?? orientedHeight, 1))
        return OutputShape.presets.first { abs($0.aspect - aspect) < 0.01 }?.id ?? "custom"
    }

    // largest output of the shape that fits the oriented capture, so nothing is upscaled
    mutating func setOutputShape(_ id: String) {
        let zoom = cropZoom, center = cropCenter
        guard id == "camera" || OutputShape.presets.contains(where: { $0.id == id }) else { return }
        fitOutput(to: id)
        refitCrop(zoom: zoom, center: center)
    }

    // presets refit to the turned camera; custom sizes stay as typed
    mutating func setRotation(_ degrees: Int) {
        let shape = outputShape, zoom = cropZoom, center = cropCenter
        rotate = degrees
        fitOutput(to: shape)
        refitCrop(zoom: zoom, center: center)
    }

    private mutating func fitOutput(to id: String) {
        if id == "camera" {
            output_width = nil
            output_height = nil
        } else if let shape = OutputShape.presets.first(where: { $0.id == id }) {
            let width = Double(orientedWidth), height = Double(max(orientedHeight, 1))
            let wide = width / height > shape.aspect
            func even(_ value: Double) -> Int { max(16, Int(value / 2) * 2) }
            output_width = even(wide ? height * shape.aspect : width)
            output_height = even(wide ? height : width / shape.aspect)
        }
    }

    // a manual crop keeps its zoom and center; untracked output fills the shape instead of padding
    private mutating func refitCrop(zoom: Double, center: CGPoint) {
        if crop != nil || (!tracking && fullCropSize != CGSize(width: 1, height: 1)) {
            setCrop(zoom: zoom, center: center)
        }
    }

    // largest crop with the output aspect, as fractions of the oriented camera frame
    var fullCropSize: CGSize {
        let source = Double(orientedWidth) / Double(max(orientedHeight, 1))
        let output = Double(output_width ?? orientedWidth) / Double(max(output_height ?? orientedHeight, 1))
        guard source.isFinite, output.isFinite, source > 0, output > 0 else { return CGSize(width: 1, height: 1) }
        return source > output ? CGSize(width: output / source, height: 1) : CGSize(width: 1, height: source / output)
    }

    var cropZoom: Double {
        guard let crop, crop.count == 4, crop[3] > 0 else { return 1 }
        return min(max(fullCropSize.height / crop[3], 1), 4)
    }

    var cropCenter: CGPoint {
        guard let crop, crop.count == 4 else { return CGPoint(x: 0.5, y: 0.5) }
        return CGPoint(x: crop[0] + crop[2] / 2, y: crop[1] + crop[3] / 2)
    }

    // keeps the output aspect and the whole crop inside the frame
    mutating func setCrop(zoom: Double, center: CGPoint) {
        let full = fullCropSize
        let scale = min(max(zoom, 1), 4)
        let width = max(full.width / scale, 0.02), height = max(full.height / scale, 0.02)
        let x = min(max(center.x - width / 2, 0), 1 - width)
        let y = min(max(center.y - height / 2, 0), 1 - height)
        func rounded(_ value: Double) -> Double { (value * 10_000).rounded() / 10_000 }
        crop = [rounded(x), rounded(y), rounded(width), rounded(height)]
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

struct BuiltInBackground: Identifiable {
    let id: String
    let title: String
    let url: URL
    let image: NSImage

    static let catalog: [BuiltInBackground] = [
        ("warm-study", "Warm study"),
        ("quiet-office", "Quiet office"),
        ("soft-shelves", "Soft shelves")
    ].compactMap { id, title in
        guard let url = Bundle.main.url(forResource: id, withExtension: "jpg", subdirectory: "Backgrounds"),
              let image = NSImage(contentsOf: url) else { return nil }
        return BuiltInBackground(id: id, title: title, url: url, image: image)
    }
}

enum OBSReadiness {
    case ready, notInstalled, setupRequired

    static func assess(models: [String], installed: Bool) -> OBSReadiness {
        // modern OBS extension exposes this model; legacy plugins are incompatible
        if models.contains(where: { $0.caseInsensitiveCompare("OBS Camera Extension") == .orderedSame }) { return .ready }
        return installed ? .setupRequired : .notInstalled
    }

    var title: String {
        switch self {
        case .ready: return "OBS Virtual Camera ready"
        case .notInstalled: return "OBS not installed"
        case .setupRequired: return "OBS Virtual Camera setup needed"
        }
    }

    var guidance: String {
        let settings = ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 15
            ? "General > Login Items & Extensions > Camera Extensions"
            : "Privacy & Security > Security"
        return "Preview works without OBS. To share video, install OBS 30 or newer, open it and click Start Virtual Camera. Allow its camera extension in System Settings > \(settings), then restart OBS. Stop its Virtual Camera and close OBS before starting Webcam Mods."
    }
}

@MainActor
final class SessionModel: ObservableObject {
    static weak var current: SessionModel?
    @Published var config = Configuration() {
        didSet {
            guard config != oldValue else { return }
            if previewView == "mask" && !maskAvailable { previewView = "output" }
            pushLiveSettings()
        }
    }
    @Published var cameras: [Camera] = []
    @Published var profiles: [Profile] = []
    @Published var selectedProfile = ""
    @Published var profileName = ""
    @Published var state = "idle" {
        didSet {
            if !previewing || (state == "starting" && oldValue != "starting") { clearPreview() }
            if !previewing {
                stats = nil
                comparing = false
                paused = false
                cancelWhitePick()
            }
            if !active { endLiveSession() }
        }
    }
    @Published var outputMode = "preview"
    @Published var outputFPS: Double?
    @Published var obsReadiness = OBSReadiness.setupRequired
    @Published var previewImage: NSImage?
    @Published var previewError: String?
    // output, source (camera before framing and effects) or mask
    @Published var previewView = "output" {
        didSet {
            guard previewView != oldValue else { return }
            comparing = false
            clearPreview()
        }
    }
    // while held, Output shows the same framing without background or image effects;
    // the last picture stays up until the other view's first frame arrives
    @Published var comparing = false
    var requestedView: String { comparing && previewView == "output" ? "original" : previewView }
    // click-to-white-balance: the next click in Camera view sets temperature and tint
    @Published var pickingWhite = false
    private var viewBeforePick: String?
    // a paused session keeps the output open and sends the loading picture with the camera off
    @Published var paused = false
    // normalized boxes drawn over the preview, never into the video
    @Published var previewGuides: [String: CGRect] = [:]
    @Published var stats: SessionStats?
    private var statsPending = false
    private var statsRequestedAt: Date?
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
    // settings the running session last accepted; nil while stopped
    @Published private(set) var sessionConfig: Configuration?
    private var sessionOutputMode = "preview"
    private var liveUpdateInFlight = false
    private var liveUpdateQueued = false
    private var restartAfterStop = false
    private var startAfterInventory = false

    init() { Self.current = self }
    var hasWorker: Bool { process != nil }

    var selectedBackground: BuiltInBackground? {
        BuiltInBackground.catalog.first { $0.url.path == config.image_path }
    }

    func selectBackground(_ background: BuiltInBackground) {
        config.image_path = background.url.path
    }

    func prepareImageBackground() {
        if config.effect == "image", config.image_path.isEmpty,
           let background = BuiltInBackground.catalog.first {
            selectBackground(background)
        }
    }

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
        previewGuides = [:]
        previewError = nil
    }

    var maskAvailable: Bool { ["blur", "color", "image", "spotlight"].contains(config.effect) }

    func pollPreview(visible: Bool) {
        if previewVisible != visible {
            previewVisible = visible
            if !visible { clearPreview() }
        }
        guard visible, connected, previewing, !previewPending else { return }
        previewPending = true
        let generation = previewGeneration
        request("preview.get", params: ["view": requestedView]) { [weak self] result in
            guard let self else { return }
            self.previewPending = false
            guard self.previewVisible, self.previewing, generation == self.previewGeneration else { return }
            self.acceptPreview(result)
        }
    }

    func beginWhitePick() {
        guard previewing, !pickingWhite else { return }
        viewBeforePick = previewView
        previewView = "source"
        pickingWhite = true
    }

    func cancelWhitePick() {
        guard pickingWhite else { return }
        pickingWhite = false
        if let view = viewBeforePick { previewView = view }
        viewBeforePick = nil
    }

    // point is a fraction of the camera picture; the worker samples the raw frame
    func pickWhite(at point: CGPoint) {
        guard pickingWhite else { return }
        cancelWhitePick()
        let x = min(max(point.x, 0), 1), y = min(max(point.y, 0), 1)
        request("session.white_balance", params: ["x": x, "y": y]) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let value):
                guard let balance = value as? [String: Any],
                      let temperature = (balance["temperature"] as? NSNumber)?.intValue, (-100...100).contains(temperature),
                      let tint = (balance["tint"] as? NSNumber)?.intValue, (-100...100).contains(tint) else {
                    self.error = "Invalid white balance from worker. Reinstall app if this repeats."
                    return
                }
                self.config.temperature = temperature
                self.config.tint = tint
            case .failure(let issue):
                self.error = issue.localizedDescription
            }
        }
    }

    // about once a second while the window shows a running session
    func pollStats(visible: Bool, now: Date = Date()) {
        guard visible, connected, previewing, !statsPending,
              statsRequestedAt.map({ now.timeIntervalSince($0) >= 1 }) ?? true else { return }
        statsPending = true
        statsRequestedAt = now
        request("session.stats") { [weak self] result in
            guard let self else { return }
            self.statsPending = false
            guard self.previewing else { return }
            self.acceptStats(result)
        }
    }

    private func acceptStats(_ result: Result<Any, Error>) {
        guard case .success(let value) = result, let data = value as? [String: Any] else {
            stats = nil
            return
        }
        func number(_ key: String) -> Double? {
            (data[key] as? NSNumber).map(\.doubleValue).flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
        }
        stats = SessionStats(processedFPS: number("processed_fps"), sentFPS: number("sent_fps"), effectMS: number("effect_ms"))
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
            if let view = frame["view"] as? String, view != requestedView { return }
            var guides: [String: CGRect] = [:]
            if let raw = frame["guides"] {
                guard let boxes = raw as? [String: Any], boxes.count <= 8 else {
                    throw failure("Invalid preview guides. Reinstall app if this repeats.")
                }
                for (name, value) in boxes {
                    // long decimals decode as NSDecimalNumber, which does not cast to Double
                    guard let box = (value as? [NSNumber])?.map(\.doubleValue), box.count == 4,
                          box.allSatisfy({ $0.isFinite && (-1...2).contains($0) }) else {
                        throw failure("Invalid preview guides. Reinstall app if this repeats.")
                    }
                    guides[name] = CGRect(x: box[0], y: box[1], width: box[2], height: box[3])
                }
            }
            previewImage = NSImage(cgImage: image, size: NSSize(width: bitmap.pixelsWide, height: bitmap.pixelsHigh))
            previewGuides = guides
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

    var restartRequired: Bool {
        guard active, let running = sessionConfig else { return false }
        return outputMode != sessionOutputMode || config.needsRestart(from: running)
    }

    private func endLiveSession() {
        sessionConfig = nil
        liveUpdateInFlight = false
        liveUpdateQueued = false
        if restartAfterStop, state == "idle" {
            restartAfterStop = false
            startAfterInventory = true
            refreshCameras()
        } else if state == "error" {
            restartAfterStop = false
        }
    }

    func pushLiveSettings() {
        guard previewing, connected, let running = sessionConfig else { return }
        let live = config.withRestartFields(from: running)
        guard live != running else { return }
        guard !liveUpdateInFlight else { liveUpdateQueued = true; return }
        liveUpdateInFlight = true
        sessionConfig = live
        request("session.update", params: ["config": live.json]) { [weak self] result in
            guard let self, self.liveUpdateInFlight else { return }
            self.liveUpdateInFlight = false
            if case .failure(let issue) = result {
                if self.sessionConfig == live { self.sessionConfig = running }
                self.error = issue.localizedDescription
            }
            if self.liveUpdateQueued {
                self.liveUpdateQueued = false
                self.pushLiveSettings()
            }
        }
    }

    func restart() {
        guard active, state != "stopping" else { return }
        restartAfterStop = true
        stop()
    }

    var previewing: Bool { ["starting", "running"].contains(state) }
    var active: Bool { ["starting", "running", "stopping"].contains(state) }
    var outputUnavailable: Bool { outputMode == "virtualcam" && obsReadiness != .ready }
    var previewInterval: TimeInterval {
        let requested = config.output_fps ?? config.fps
        let fps = outputFPS ?? (config.repeat_frames ? requested : min(config.fps, requested))
        return 1 / (fps.isFinite && (1...240).contains(fps) ? fps : Configuration().fps)
    }

    func refreshOBS() {
        let external: AVCaptureDevice.DeviceType
        if #available(macOS 14, *) { external = .external }
        else { external = .externalUnknown }
        let devices = AVCaptureDevice.DiscoverySession(deviceTypes: [external], mediaType: .video, position: .unspecified).devices
        obsReadiness = OBSReadiness.assess(
            models: devices.filter { $0.isConnected }.map { $0.modelID },
            installed: NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.obsproject.obs-studio") != nil
        )
    }
    var build: String {
        let info = Bundle.main.infoDictionary ?? [:]
        return "\(info["CFBundleShortVersionString"] as? String ?? "unknown") (\(info["BuildCommit"] as? String ?? "unknown"))"
    }
    var buildDate: String { Bundle.main.object(forInfoDictionaryKey: "BuildDate") as? String ?? "unknown" }

    func connect() {
        guard process == nil, !Self.snapshotMode else { return }
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
                    self.request("profiles.seed_defaults") { [weak self] result in
                        if case .failure(let issue) = result { self?.error = issue.localizedDescription }
                        self?.refresh()
                    }
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
                outputFPS = (data["output_fps"] as? NSNumber)?.doubleValue
                paused = data["paused"] as? Bool ?? false
                error = data["error"] as? String
            } else if message["event"] as? String == "warning", let data = message["data"] as? [String: Any] {
                error = data["message"] as? String
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

    // offscreen renders never start the worker or open a camera
    static var snapshotMode = false

    @MainActor static func renderSnapshots(to directory: URL, image: NSImage?) throws {
        snapshotMode = true
        // accessory windows never activate the app or take focus from the user
        NSApplication.shared.setActivationPolicy(.accessory)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        func render(_ name: String, width: CGFloat, height: CGFloat, _ configure: (SessionModel) -> Void) throws {
            let model = SessionModel()
            model.connected = true
            model.backendVersion = "snapshot"
            model.cameras = [Camera(index: 0, name: "FaceTime HD Camera", id: "snapshot-camera")]
            model.inventoryCapture = model.config.capture
            model.config.camera_id = "snapshot-camera"
            configure(model)
            let size = NSSize(width: width, height: height)
            let view = NSHostingView(rootView: MainWindow(model: model))
            // borderless windows may sit off every display; ordering one in lets AppKit controls draw
            let window = NSWindow(contentRect: NSRect(x: -20_000, y: -20_000, width: size.width, height: size.height), styleMask: [.borderless], backing: .buffered, defer: false)
            window.backgroundColor = .windowBackgroundColor
            window.contentView = view
            window.orderFrontRegardless()
            defer { window.orderOut(nil) }
            RunLoop.main.run(until: Date().addingTimeInterval(0.5))
            // window server capture draws AppKit controls that cacheDisplay leaves blank;
            // the SDK hides this API, but capturing the app's own window needs no permission
            typealias WindowCapture = @convention(c) (CGRect, UInt32, UInt32, UInt32) -> Unmanaged<CGImage>?
            guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "CGWindowListCreateImage"),
                  let image = unsafeBitCast(symbol, to: WindowCapture.self)(.null, 1 << 3, UInt32(window.windowNumber), 1 << 0 | 1 << 3)?.takeRetainedValue(),
                  let data = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
                throw NSError(domain: "WebcamModsSnapshot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Could not render \(name)"])
            }
            try data.write(to: directory.appendingPathComponent("\(name).png"))
        }
        func running(_ model: SessionModel, view: String) {
            model.state = "running"
            model.sessionConfig = model.config
            model.previewView = view
            model.previewImage = image
            model.stats = SessionStats(processedFPS: 29.9, sentFPS: 30, effectMS: 11.4)
        }
        try render("desktop-output", width: 1100, height: 720) { model in
            model.config.effect = "blur"
            running(model, view: "output")
        }
        try render("desktop-camera-guides", width: 1100, height: 720) { model in
            model.config.track = true
            running(model, view: "source")
            model.previewGuides = ["face": CGRect(x: 0.36, y: 0.12, width: 0.26, height: 0.34), "framing": CGRect(x: 0.2, y: 0.02, width: 0.6, height: 0.6)]
        }
        try render("desktop-camera-crop", width: 1100, height: 820) { model in
            model.config.track = true
            model.config.setCrop(zoom: 1.6, center: CGPoint(x: 0.45, y: 0.4))
            running(model, view: "source")
            model.previewGuides = ["face": CGRect(x: 0.36, y: 0.12, width: 0.26, height: 0.34), "framing": CGRect(x: 0.2, y: 0.08, width: 0.52, height: 0.52)]
        }
        try render("desktop-compare", width: 1100, height: 720) { model in
            model.config.effect = "blur"
            running(model, view: "output")
            model.comparing = true
        }
        try render("desktop-color-pick", width: 1100, height: 900) { model in
            model.config.exposure = 0.3
            model.config.temperature = 18
            model.config.saturation = 10
            model.config.auto_light = 40
            model.config.effect = "spotlight"
            model.config.look = "film"
            model.config.look_strength = 70
            running(model, view: "output")
            model.beginWhitePick()
            model.previewImage = image
        }
        try render("desktop-image-background", width: 1100, height: 1000) { model in
            if let background = BuiltInBackground.catalog.first { model.selectBackground(background) }
            model.config.effect = "image"
            model.config.image_x = 0.3
            running(model, view: "output")
        }
        try render("narrow-color-background", width: 440, height: 900) { model in
            model.config.effect = "color"
            model.config.background_color = "#2E6B5A"
            running(model, view: "output")
        }
        try render("narrow-camera-guides", width: 440, height: 900) { model in
            model.config.track = true
            running(model, view: "source")
            model.previewGuides = ["face": CGRect(x: 0.36, y: 0.12, width: 0.26, height: 0.34), "framing": CGRect(x: 0.2, y: 0.02, width: 0.6, height: 0.6)]
        }
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
        let backgrounds = BuiltInBackground.catalog
        try check(backgrounds.count == 3, "All built-in backgrounds bundled and readable")
        for background in backgrounds {
            let bitmap = NSBitmapImageRep(data: try Data(contentsOf: background.url))
            try check(bitmap?.pixelsWide == 1600 && bitmap?.pixelsHigh == 900, "Built-in background dimensions: \(background.id)")
            model.selectBackground(background)
            model.config.effect = "image"
            model.config.image_blur = true
            let decoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(model.config))
            try check(decoded.image_path == background.url.path && model.selectedBackground?.id == background.id, "Background selection survives profile encoding")
            try check(decoded.image_blur && decoded.blur_kernel == model.config.blur_kernel, "Image blur survives profile encoding")
        }
        model.config.image_path = "/tmp/custom-background.jpg"
        model.prepareImageBackground()
        try check(model.selectedBackground == nil && model.config.image_path == "/tmp/custom-background.jpg", "Custom image is preserved when entering image mode")
        model.config.image_path = ""
        model.prepareImageBackground()
        try check(model.selectedBackground?.id == backgrounds.first?.id, "Empty image mode gets a built-in background")
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
        model.state = "starting"
        model.connected = true
        model.pollPreview(visible: true)
        let startupReply = try JSONSerialization.data(withJSONObject: ["id": model.nextID, "result": frame])
        model.consume(startupReply + Data([10]))
        try check(model.previewImage != nil, "Startup polls and displays shared status frames")
        model.state = "starting"
        try check(model.previewImage != nil, "Startup cadence updates preserve loading picture")
        model.state = "running"
        try check(model.previewImage != nil, "First live frame transition preserves picture")
        model.pollPreview(visible: false)
        var noiseConfig = Configuration()
        noiseConfig.signal_pattern = "noise"
        let noiseDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(noiseConfig))
        try check(noiseDecoded.signal_pattern == "noise", "Loading picture survives profile encoding")
        var mirrorConfig = Configuration()
        mirrorConfig.mirror = true
        let mirrorDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(mirrorConfig))
        try check(mirrorDecoded.mirror && mirrorDecoded != Configuration(), "Mirror survives profile encoding")
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
        try check(OBSReadiness.assess(models: [], installed: false) == .notInstalled, "Missing OBS detected")
        try check(OBSReadiness.assess(models: ["OBS Virtual Camera"], installed: true) == .setupRequired, "Legacy OBS camera is not ready")
        try check(OBSReadiness.assess(models: ["obs camera extension"], installed: false) == .ready, "Modern extension works without OBS app running or installed")
        model.obsReadiness = .notInstalled
        model.outputMode = "preview"
        try check(!model.outputUnavailable, "Missing OBS does not block preview")
        model.outputMode = "virtualcam"
        try check(model.outputUnavailable, "Missing OBS blocks virtual output")
        model.obsReadiness = .ready
        try check(!model.outputUnavailable, "Ready extension enables virtual output")
        model.config.fps = 30
        model.config.output_fps = 60
        model.config.repeat_frames = true
        model.outputFPS = nil
        try check(model.previewInterval == 1 / 60.0, "Repeat preview follows requested output cadence before negotiation")
        model.config.repeat_frames = false
        try check(model.previewInterval == 1 / 30.0, "Direct preview respects capture cadence before negotiation")
        model.consume(Data("{\"event\":\"status\",\"data\":{\"state\":\"running\",\"output_fps\":29.97}}\n".utf8))
        try check(model.previewInterval == 1 / 29.97, "Preview follows negotiated output FPS")
        model.consume(Data("{\"event\":\"status\",\"data\":{\"state\":\"running\",\"output_fps\":29.970029970029969}}\n".utf8))
        try check(abs(model.previewInterval - 1001 / 30000.0) < 1e-9, "Long decimal output FPS still decodes")
        model.consume(Data("{\"event\":\"status\",\"data\":{\"state\":\"idle\"}}\n".utf8))
        try check(model.outputFPS == nil, "Idle clears negotiated output cadence")
        _ = pipe.fileHandleForReading.availableData
        func lastRequest() throws -> [String: Any]? {
            let lines = pipe.fileHandleForReading.availableData.split(separator: 10)
            return try lines.last.flatMap { try JSONSerialization.jsonObject(with: Data($0)) as? [String: Any] }
        }
        model.config = Configuration()
        model.outputMode = "preview"
        model.state = "running"
        model.sessionConfig = Configuration()
        model.sessionOutputMode = "preview"
        let liveID = model.nextID + 1
        model.config.brightness = 40
        var live = try lastRequest()
        let liveParams = live?["params"] as? [String: Any]
        try check(live?["method"] as? String == "session.update" && (liveParams?["config"] as? [String: Any])?["brightness"] as? Int == 40, "Live setting sends session update")
        model.config.width = 1280
        try check(model.nextID == liveID && model.restartRequired, "Capture size waits for restart instead of live update")
        model.config.brightness = 50
        try check(model.nextID == liveID, "One live update in flight")
        model.consume(Data("{\"id\":\(liveID),\"result\":{\"state\":\"running\"}}\n".utf8))
        live = try lastRequest()
        let queued = (live?["params"] as? [String: Any])?["config"] as? [String: Any]
        try check(model.nextID == liveID + 1 && queued?["brightness"] as? Int == 50 && queued?["width"] as? Int == 640, "Queued live update keeps running capture settings")
        model.consume(Data("{\"id\":\(liveID + 1),\"error\":\"could not apply\"}\n".utf8))
        try check(model.error == "could not apply" && model.sessionConfig?.brightness == 40, "Rejected live update restores accepted settings")
        model.consume(Data("{\"event\":\"warning\",\"data\":{\"message\":\"Could not apply settings: model\"}}\n".utf8))
        try check(model.error == "Could not apply settings: model", "Worker warnings surface")
        model.config.width = 640
        model.config.input_device = 3
        model.sessionConfig?.camera_id = "same"
        model.config.camera_id = "same"
        try check(!model.restartRequired, "Camera index renumbering does not require restart")
        model.outputMode = "virtualcam"
        try check(model.restartRequired, "Output destination change requires restart")
        model.state = "idle"
        try check(model.sessionConfig == nil && !model.restartRequired, "Stopping clears live session state")
        model.outputMode = "preview"
        model.state = "running"
        model.previewView = "source"
        model.pollPreview(visible: true)
        let viewRequest = try lastRequest()
        try check((viewRequest?["params"] as? [String: Any])?["view"] as? String == "source", "Preview requests the chosen view")
        let guided: [String: Any] = ["jpeg": jpeg, "width": 2, "height": 2, "view": "source", "guides": ["face": [0.25, 0.5, 0.25, 0.25], "crop": [0.1, 0.2, 0.30000000000000004, 0.4]]]
        model.consume(try JSONSerialization.data(withJSONObject: ["id": model.nextID, "result": guided]) + Data([10]))
        try check(model.previewImage != nil && model.previewGuides["face"] == CGRect(x: 0.25, y: 0.5, width: 0.25, height: 0.25) && model.previewGuides["crop"] != nil, "Source view decodes normalized guides, including long decimals")
        model.previewView = "output"
        try check(model.previewImage == nil && model.previewGuides.isEmpty, "Changing view clears the previous picture and guides")
        model.acceptPreview(.success(guided))
        try check(model.previewImage == nil, "Frames for another view are ignored")
        model.previewView = "source"
        model.acceptPreview(.success(["jpeg": jpeg, "width": 2, "height": 2, "view": "source", "guides": ["face": [0.1, 0.2]]]))
        try check(model.previewError != nil && model.previewGuides.isEmpty, "Malformed guides are rejected")
        model.config.effect = "blur"
        model.previewView = "mask"
        model.config.effect = "plain"
        try check(model.previewView == "output" && !model.maskAvailable, "Mask view falls back when segmentation turns off")
        model.acceptPreview(.success(["jpeg": jpeg, "width": 2, "height": 2, "view": "output"]))
        let processed = model.previewImage
        model.comparing = true
        model.pollPreview(visible: true)
        let compareRequest = try lastRequest()
        try check((compareRequest?["params"] as? [String: Any])?["view"] as? String == "original" && processed != nil && model.previewImage === processed, "Compare requests the original view and keeps the last picture")
        model.acceptPreview(.success(["jpeg": jpeg, "width": 2, "height": 2, "view": "output"]))
        try check(model.previewImage === processed, "Late output frames are ignored while comparing")
        model.consume(try JSONSerialization.data(withJSONObject: ["id": model.nextID, "result": ["jpeg": jpeg, "width": 2, "height": 2, "view": "original"]]) + Data([10]))
        try check(model.previewImage != nil && model.previewImage !== processed, "Original frames show while comparing")
        model.previewView = "source"
        try check(!model.comparing && model.requestedView == "source", "Switching view ends compare")
        model.previewView = "output"
        model.comparing = true
        model.state = "idle"
        try check(!model.comparing, "Stopping ends compare")
        model.state = "running"
        var colored = Configuration()
        colored.exposure = 0.5
        colored.sharpness = 30
        colored.auto_light = 60
        let coloredDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(colored))
        try check(coloredDecoded.exposure == 0.5 && coloredDecoded.auto_light == 60 && coloredDecoded.colorAdjusted && !colored.needsRestart(from: Configuration()) && (Configuration().json["tint"] as? Int) == 0, "Color settings encode and apply live")
        colored.resetColor()
        try check(!colored.colorAdjusted && colored == Configuration(), "Reset color restores neutral settings")
        var spotlight = Configuration()
        spotlight.effect = "spotlight"
        spotlight.spotlight_dim = 80
        let spotlightDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(spotlight))
        var graded = Configuration()
        graded.look = "film"
        graded.look_strength = 70
        let gradedDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(graded))
        try check(gradedDecoded.look == "film" && gradedDecoded.look_strength == 70 && gradedDecoded.look_path.isEmpty && !graded.needsRestart(from: Configuration()) && (Configuration().json["look"] as? String) == "none", "Looks encode and apply live")
        try check(ControlPanel.looks.allSatisfy { !["none", "custom"].contains($0) } && ControlPanel.looks.count == 6, "Built-in looks list")
        try check(spotlightDecoded.spotlight_dim == 80 && spotlightDecoded.spotlight_lift == 20 && !spotlight.needsRestart(from: Configuration()), "Spotlight settings encode and apply live")
        model.previewView = "output"
        model.beginWhitePick()
        try check(model.pickingWhite && model.previewView == "source", "White pick switches to Camera view")
        model.pickWhite(at: CGPoint(x: 1.4, y: 0.25))
        let pickParams = (try lastRequest())?["params"] as? [String: Any]
        try check((pickParams?["x"] as? Double) == 1 && (pickParams?["y"] as? Double) == 0.25 && !model.pickingWhite && model.previewView == "output", "White pick sends a clamped camera point and restores the view")
        model.consume(Data("{\"id\":\(model.nextID),\"result\":{\"temperature\":14,\"tint\":-6}}\n".utf8))
        try check(model.config.temperature == 14 && model.config.tint == -6, "White pick sets warmth and tint")
        model.beginWhitePick()
        model.pickWhite(at: CGPoint(x: 0.5, y: 0.5))
        model.consume(Data("{\"id\":\(model.nextID),\"result\":{\"temperature\":400,\"tint\":0}}\n".utf8))
        try check(model.config.temperature == 14 && model.error != nil, "Out of range white balance is rejected")
        model.error = nil
        model.beginWhitePick()
        model.cancelWhitePick()
        try check(!model.pickingWhite && model.previewView == "output", "Cancel white pick restores the view")
        let statsID = model.nextID + 1
        let statsTime = Date()
        model.pollStats(visible: true, now: statsTime)
        model.pollStats(visible: true, now: statsTime.addingTimeInterval(2))
        let statsRequest = try lastRequest()
        try check(model.nextID == statsID && statsRequest?["method"] as? String == "session.stats", "One stats request in flight")
        model.consume(Data("{\"id\":\(statsID),\"result\":{\"processed_fps\":29.94,\"sent_fps\":30,\"effect_ms\":null}}\n".utf8))
        try check(model.stats?.summary == "Processed 29.9 fps, sent 30 fps, effects --", "Stats decode and format")
        model.pollStats(visible: true, now: statsTime.addingTimeInterval(0.5))
        try check(model.nextID == statsID, "Stats poll at most once a second")
        model.state = "idle"
        try check(model.stats == nil, "Stopping clears stats")
        var tuned = Configuration()
        tuned.track_face_height = 0.3
        tuned.track_follow_seconds = 1.5
        let tunedDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(tuned))
        try check(tunedDecoded.track_face_height == 0.3 && tunedDecoded.track_follow_seconds == 1.5 && tuned.json["track_deadzone"] as? Double == 0.08, "Framing preferences survive profile encoding")
        tuned.resetFramingPreferences()
        try check(tuned == Configuration(), "Default framing restores tracking preferences")
        try check(!tuned.withRestartFields(from: Configuration()).needsRestart(from: tunedDecoded), "Framing preferences apply live")
        var framing = Configuration()
        try check(framing.fullCropSize == CGSize(width: 1, height: 1) && framing.cropZoom == 1, "Matching aspect uses the whole frame")
        framing.output_width = 1280
        framing.output_height = 720
        framing.setCrop(zoom: 2, center: CGPoint(x: 0.5, y: 0.5))
        try check(framing.crop == [0.25, 0.3125, 0.5, 0.375] && abs(framing.cropZoom - 2) < 0.001, "Crop keeps output aspect at the requested zoom")
        framing.setCrop(zoom: 8, center: CGPoint(x: -1, y: 2))
        try check(framing.crop == [0, 0.8125, 0.25, 0.1875] && framing.cropZoom == 4, "Crop clamps zoom and position inside the frame")
        let framingDecoded = try JSONDecoder().decode(Configuration.self, from: JSONEncoder().encode(framing))
        try check(framingDecoded.crop == framing.crop && Configuration().json["crop"] == nil, "Crop survives profile encoding and stays absent by default")
        model.state = "running"
        model.sessionConfig = model.config
        model.config.setCrop(zoom: 1.5, center: CGPoint(x: 0.4, y: 0.5))
        let cropUpdate = ((try lastRequest())?["params"] as? [String: Any])?["config"] as? [String: Any]
        let sentCrop = (cropUpdate?["crop"] as? [NSNumber])?.map(\.doubleValue) ?? []
        try check(sentCrop.count == 4 && zip(sentCrop, model.config.crop ?? []).allSatisfy { abs($0 - $1) < 1e-9 } && !model.restartRequired, "Crop applies live")
        var oriented = Configuration()
        oriented.flip_vertical = true
        try check(!oriented.needsRestart(from: Configuration()) && (Configuration().json["rotate"] as? Int) == 0, "Vertical flip applies live")
        oriented.rotate = 270
        try check(oriented.needsRestart(from: Configuration()) && oriented.orientedWidth == 480 && oriented.outputShape == "camera", "Rotation restarts and turns the default output")
        var shaped = Configuration()
        shaped.width = 1280
        shaped.height = 720
        shaped.setOutputShape("9:16")
        try check(shaped.output_width == 404 && shaped.output_height == 720 && shaped.outputShape == "9:16" && abs((shaped.crop?[2] ?? 0) - 0.3156) < 0.001, "Portrait shape fits the camera and fills without bars")
        shaped.setRotation(90)
        try check(shaped.output_width == 720 && shaped.output_height == 1280 && shaped.crop == [0, 0, 1, 1], "Rotation refits a preset shape and crop")
        shaped.setOutputShape("camera")
        try check(shaped.output_width == nil && shaped.output_height == nil && shaped.cropZoom == 1, "Camera shape follows rotated capture")
        var trackedShape = Configuration()
        trackedShape.track = true
        trackedShape.setOutputShape("16:9")
        try check(trackedShape.output_width == 640 && trackedShape.output_height == 360 && trackedShape.crop == nil, "Tracking frames a new shape without a fixed crop")
        trackedShape.output_width = 1000
        trackedShape.output_height = 500
        try check(trackedShape.outputShape == "custom", "Typed output size shows as custom")
        var painted = Configuration()
        let defaultGray = painted.backgroundColor.usingColorSpace(.sRGB)
        try check(abs((defaultGray?.greenComponent ?? 0) - 192 / 255) < 0.001, "Gray level shows as the starting background color")
        painted.setBackgroundColor(NSColor(srgbRed: 0, green: 0.5, blue: 1, alpha: 1))
        try check(painted.background_color == "#0080FF" && painted.json["background_color"] as? String == "#0080FF" && Configuration().json["background_color"] == nil, "Background color encodes as hex and stays absent by default")
        painted.image_x = 0.2
        try check(!painted.needsRestart(from: Configuration()) && painted.json["image_x"] as? Double == 0.2, "Background color and image position apply live")
        let switcher = SessionModel()
        let switchPipe = Pipe()
        switcher.input = switchPipe.fileHandleForWriting
        switcher.connected = true
        switcher.state = "running"
        switcher.sessionConfig = switcher.config
        var livePick = switcher.config
        livePick.brightness = 30
        var restartPick = switcher.config
        restartPick.width = 1280
        restartPick.height = 720
        switcher.profiles = [Profile(name: "Bright", config: livePick), Profile(name: "Wide", config: restartPick)]
        switcher.switchProfile("Bright")
        let liveSwitch = String(decoding: switchPipe.fileHandleForReading.availableData, as: UTF8.self)
        try check(switcher.selectedProfile == "Bright" && switcher.config.brightness == 30 && liveSwitch.contains("\"session.update\"") && !liveSwitch.contains("\"stop\"") && switcher.state == "running", "Menu profile switch applies live fields")
        switcher.switchProfile("Wide")
        let restartSwitch = String(decoding: switchPipe.fileHandleForReading.availableData, as: UTF8.self)
        try check(switcher.selectedProfile == "Wide" && switcher.state == "stopping" && restartSwitch.contains("\"stop\""), "Menu profile switch restarts for capture changes")
        try switchPipe.fileHandleForWriting.close()
        try switchPipe.fileHandleForReading.close()
        SessionModel.current = model
        let pauseID = model.nextID + 1
        model.togglePause()
        let pauseRequest = try lastRequest()
        try check(model.paused && pauseRequest?["method"] as? String == "session.pause" && (pauseRequest?["params"] as? [String: Any])?["paused"] as? Bool == true, "Pause shows at once and asks the worker")
        model.consume(Data("{\"id\":\(pauseID),\"result\":{\"state\":\"running\"}}\n".utf8))
        try check(!model.paused, "Worker status decides pause")
        model.consume(Data("{\"event\":\"status\",\"data\":{\"state\":\"running\",\"paused\":true}}\n".utf8))
        try check(model.paused, "Status event carries pause")
        model.state = "idle"
        try check(!model.paused, "Stopping clears pause")
        model.togglePause()
        try check(!model.paused && model.nextID == pauseID, "Pause needs a running camera")
        model.state = "idle"
        try pipe.fileHandleForWriting.close()
        try pipe.fileHandleForReading.close()
        try helperSelfTest()
        print("Native model self-test passed (JSONL, profiles, backgrounds, camera identity, preview lifecycle/cadence/views/guides, OBS readiness, live updates, stats, orientation, compare, color, spotlight, looks, pause, menu profiles, background color).")
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
        var imageConfig = Configuration()
        imageConfig.effect = "image"
        imageConfig.image_path = BuiltInBackground.catalog[0].url.path
        imageConfig.image_blur = true
        imageConfig.blur_kernel = 15
        let requests: [[String: Any]] = [
            ["id": 1, "method": "hello"],
            ["id": 2, "method": "profiles.seed_defaults"],
            ["id": 3, "method": "profiles.save", "params": ["name": "Native test", "config": imageConfig.json]],
            ["id": 4, "method": "profiles.list"],
            ["id": 5, "method": "preview.get", "params": [:]],
            ["id": 6, "method": "shutdown"]
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
        guard helper.terminationStatus == 0, lines.count == 6 else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper failed"])
        }
        let messages = try lines.map { try JSONSerialization.jsonObject(with: Data($0)) as? [String: Any] }
        guard let hello = messages[0]?["result"] as? [String: Any], hello["protocol"] as? Int == 1,
              messages[1]?["result"] as? Bool == true,
              let profiles = messages[3]?["result"] as? [[String: Any]],
              messages[4]?["result"] is NSNull else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper response mismatch"])
        }
        let profileData = try JSONSerialization.data(withJSONObject: profiles)
        let decoded = try JSONDecoder().decode([Profile].self, from: profileData)
        guard decoded.count == 6,
              let saved = decoded.first(where: { $0.name == "Native test" }), saved.config.brightness == 0, saved.config.capture == "avfoundation",
              saved.config.effect == "image", saved.config.image_path == imageConfig.image_path,
              saved.config.image_blur, saved.config.blur_kernel == 15,
              let blurred = decoded.first(where: { $0.name == "Blur + Auto Framing" }), blurred.config.effect == "blur", blurred.config.track else {
            throw NSError(domain: "WebcamModsSelfTest", code: 1, userInfo: [NSLocalizedDescriptionKey: "Real helper profile mismatch"])
        }
    }

    func refresh() {
        refreshOBS()
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
        if startAfterInventory {
            startAfterInventory = false
            start()
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

    // menu bar switching applies at once; camera or output shape changes restart
    func switchProfile(_ name: String) {
        guard name != selectedProfile || profileModified else { return }
        selectProfile(name)
        if restartRequired { restart() }
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
        refreshOBS()
        guard !outputUnavailable else { error = obsReadiness.guidance; return }
        guard !cameraUnavailable else { error = "Saved camera unavailable. Reconnect it or choose another camera."; return }
        error = nil
        outputFPS = nil
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
                self.sessionConfig = self.config
                self.sessionOutputMode = self.outputMode
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

    // shows the new state at once; the worker's status confirms it
    func togglePause() {
        guard state == "running" else { return }
        paused.toggle()
        request("session.pause", params: ["paused": paused]) { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let value):
                if let status = value as? [String: Any] { self.paused = status["paused"] as? Bool ?? false }
            case .failure(let issue):
                self.error = issue.localizedDescription
            }
        }
    }

    // system eyedropper: any pixel on screen, such as the wall in the camera preview
    func sampleBackgroundColor() {
        NSColorSampler().show { [weak self] picked in
            guard let picked else { return }
            Task { @MainActor in self?.config.setBackgroundColor(picked) }
        }
    }

    // sets path and look together so the worker never sees custom without a file
    func chooseLook() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "cube") ?? .data]
        panel.allowsMultipleSelection = false
        panel.message = "Choose a .cube color lookup table"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        var next = config
        next.look_path = url.path
        next.look = "custom"
        config = next
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
    @State private var colorExpanded: Bool
    @State private var confirmDelete = false
    @State private var showError = false

    init(model: SessionModel) {
        self.model = model
        _colorExpanded = State(initialValue: model.config.colorAdjusted)
    }

    // keep in step with LOOKS in profiles.py
    static let looks = ["warm", "cool", "mono", "fade", "vivid", "film"]

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
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Label(model.obsReadiness.title, systemImage: model.obsReadiness == .ready ? "checkmark.circle.fill" : "exclamationmark.triangle")
                                .foregroundStyle(model.obsReadiness == .ready ? .green : .orange)
                            Spacer()
                            Button("Check again", action: model.refreshOBS)
                        }
                        if model.obsReadiness != .ready {
                            Text(model.obsReadiness.guidance).foregroundStyle(.secondary)
                            HStack {
                                Link("Download OBS", destination: URL(string: "https://obsproject.com/download")!)
                                Link("Setup guide", destination: URL(string: "https://obsproject.com/kb/virtual-camera-troubleshooting")!)
                            }
                        }
                    }.font(.caption)
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
                        Text("Solid color").tag("color")
                        Text("Image").tag("image")
                        Text("Spotlight").tag("spotlight")
                        Text("Face tracking").tag("track")
                    }
                    if model.config.effect == "blur" || (model.config.effect == "image" && model.config.image_blur) {
                        Stepper("Blur: \(model.config.blur_kernel)", value: $model.config.blur_kernel, in: 1...151, step: 2)
                    }
                    if model.config.effect == "color" {
                        HStack {
                            ColorPicker("Color", selection: Binding(get: { Color(nsColor: model.config.backgroundColor) }, set: { model.config.setBackgroundColor(NSColor($0)) }), supportsOpacity: false)
                            Button { model.sampleBackgroundColor() } label: { Image(systemName: "eyedropper") }
                                .help("Pick a color from anywhere on screen, such as your wall in the preview")
                                .accessibilityLabel("Pick color from screen")
                        }
                    }
                    if model.config.effect == "spotlight" {
                        slider("Dim room", value: $model.config.spotlight_dim, range: 0...100)
                            .help("How much darker the background gets, in percent.")
                        slider("Lift you", value: $model.config.spotlight_lift, range: 0...100)
                            .help("Brightens you while black and white stay put.")
                    }
                    if model.config.effect == "image" {
                        BackgroundGallery(model: model)
                        decimalSlider("Horizontal", value: $model.config.image_x, range: 0...1, text: { "\(Int(($0 * 100).rounded()))%" })
                            .help("Which part of the image shows when its shape differs from the video, from left to right.")
                        decimalSlider("Vertical", value: $model.config.image_y, range: 0...1, text: { "\(Int(($0 * 100).rounded()))%" })
                            .help("Which part of the image shows when its shape differs from the video, from top to bottom.")
                        Toggle("Blur image background", isOn: $model.config.image_blur)
                    }
                    Toggle("Track face", isOn: $model.config.track).disabled(model.config.effect == "track")
                    if model.config.tracking {
                        VStack(alignment: .leading, spacing: 4) {
                            decimalSlider("Face size", value: $model.config.track_face_height, range: 0.1...0.9, text: { "\(Int(($0 * 100).rounded()))%" })
                                .help("Face height as a share of the picture.")
                            decimalSlider("Head height", value: $model.config.track_target_y, range: 0.2...0.8, text: { "\(Int(($0 * 100).rounded()))%" })
                                .help("Where your face sits, measured from the top of the picture.")
                            decimalSlider("Max zoom", value: $model.config.track_max_zoom, range: 1...4, text: { "\($0.formatted(.number.precision(.fractionLength(1))))x" })
                            decimalSlider("Follow", value: $model.config.track_follow_seconds, range: 0.05...3, text: { "\($0.formatted(.number.precision(.fractionLength(2)))) s" })
                                .help("How long framing takes to catch up. Shorter follows faster.")
                            decimalSlider("Steadiness", value: $model.config.track_deadzone, range: 0...0.4, text: { "\(Int(($0 * 100).rounded()))%" })
                                .help("Movement ignored before framing follows, as a share of the picture.")
                            Button("Default framing") { model.config.resetFramingPreferences() }
                        }.padding(.leading, 20)
                    }
                    slider("Brightness", value: $model.config.brightness, range: 0...255)
                    Picker("Look", selection: Binding(get: { model.config.look }, set: { look in
                        if look == "custom" { model.chooseLook() } else { model.config.look = look }
                    })) {
                        Text("None").tag("none")
                        ForEach(Self.looks, id: \.self) { look in Text(look.capitalized).tag(look) }
                        Text(model.config.look_path.isEmpty ? "Custom LUT..." : "Custom: \(URL(fileURLWithPath: model.config.look_path).deletingPathExtension().lastPathComponent)").tag("custom")
                    }.help("A finishing color grade. Custom loads a .cube lookup table file.")
                    if model.config.look != "none" {
                        HStack {
                            slider("Strength", value: $model.config.look_strength, range: 0...100)
                            if model.config.look == "custom" {
                                Button("Choose...", action: model.chooseLook).help("Pick another .cube file")
                            }
                        }
                    }
                    DisclosureGroup("Color", isExpanded: $colorExpanded) {
                        VStack(alignment: .leading, spacing: 4) {
                            slider("Low light", value: $model.config.auto_light, range: 0...100)
                                .help("Brightens dark rooms gradually; bright pictures stay as they are. 0 is off.")
                            decimalSlider("Exposure", value: $model.config.exposure, range: -2...2, text: { "\($0 > 0 ? "+" : "")\($0.formatted(.number.precision(.fractionLength(1))))" })
                                .help("Exposure in stops: +1 doubles the light.")
                            slider("Contrast", value: $model.config.contrast, range: -100...100)
                            slider("Saturation", value: $model.config.saturation, range: -100...100)
                            slider("Warmth", value: $model.config.temperature, range: -100...100)
                                .help("Positive is warmer (more orange), negative cooler (more blue).")
                            slider("Tint", value: $model.config.tint, range: -100...100)
                                .help("Positive adds magenta, negative adds green.")
                            slider("Sharpness", value: $model.config.sharpness, range: 0...100)
                            HStack {
                                Button("Pick white...", action: model.beginWhitePick).disabled(!model.previewing || model.pickingWhite)
                                    .help("Click something white or gray in the camera picture to set warmth and tint.")
                                Button("Reset color") { model.config.resetColor() }.disabled(!model.config.colorAdjusted)
                            }
                        }.padding(.top, 4)
                    }
                    Toggle("Mirror video", isOn: $model.config.mirror)
                        .help("Flip left to right. Preview and OBS Virtual Camera both show the mirrored view.")
                    Toggle("Flip upside down", isOn: $model.config.flip_vertical)
                        .help("For cameras mounted upside down.")
                    Picker("Rotate", selection: Binding(get: { model.config.rotate }, set: { model.config.setRotation($0) })) {
                        Text("0").tag(0); Text("90").tag(90); Text("180").tag(180); Text("270").tag(270)
                    }.pickerStyle(.segmented)
                        .help("Turn the camera picture clockwise, in degrees, for a sideways or upside-down camera. Applies after a restart.")
                    Picker("Shape", selection: Binding(get: { model.config.outputShape }, set: { model.config.setOutputShape($0) })) {
                        Text("Same as camera").tag("camera")
                        ForEach(OutputShape.presets) { shape in Text(shape.label).tag(shape.id) }
                        if model.config.outputShape == "custom" {
                            Text("Custom \(model.config.output_width ?? model.config.orientedWidth)x\(model.config.output_height ?? model.config.orientedHeight)").tag("custom")
                        }
                    }.help("Output picture shape. Sizes fit the camera without upscaling; edit them under Advanced. Applies after a restart.")
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text("Zoom").frame(width: 75, alignment: .leading)
                            Slider(value: Binding(get: { model.config.cropZoom }, set: { model.config.setCrop(zoom: $0, center: model.config.cropCenter) }), in: 1...4)
                            Text("\(model.config.cropZoom.formatted(.number.precision(.fractionLength(1))))x").monospacedDigit().frame(width: 36, alignment: .trailing)
                        }
                        HStack {
                            Button("Center") { model.config.setCrop(zoom: model.config.cropZoom, center: CGPoint(x: 0.5, y: 0.5)) }
                            Button("Show whole camera") { model.config.crop = nil }.disabled(model.config.crop == nil)
                        }
                        Text(model.config.crop == nil
                             ? "Zoom in to crop. Drag the box in Camera view to choose what calls see."
                             : model.config.track || model.config.effect == "track"
                             ? "Face tracking stays inside the crop. Drag the box in Camera view to move it."
                             : "Drag the box in Camera view, or pinch it, to adjust the crop.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
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
                                    model.config.output_width = inherited ? nil : model.config.orientedWidth
                                    model.config.output_height = inherited ? nil : model.config.orientedHeight
                                    model.config.output_fps = inherited ? nil : model.config.fps
                                }))
                            if model.config.output_width != nil || model.config.output_height != nil || model.config.output_fps != nil {
                                HStack {
                                    Text("Output size")
                                    TextField("Width", value: Binding(get: { model.config.output_width ?? model.config.orientedWidth }, set: { model.config.output_width = $0 }), format: .number)
                                    Text("x")
                                    TextField("Height", value: Binding(get: { model.config.output_height ?? model.config.orientedHeight }, set: { model.config.output_height = $0 }), format: .number)
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
                            Picker("Loading picture", selection: $model.config.signal_pattern) {
                                Text("TV color bars").tag("color-bars"); Text("TV static").tag("noise")
                            }
                            Toggle("Repeat latest frame", isOn: $model.config.repeat_frames)
                            Toggle("Smooth segmentation mask", isOn: $model.config.smoothing)
                        }.padding(.top, 6)
                    }
                }.disabled(!model.connected)
            }.frame(maxHeight: .infinity)
            if model.restartRequired {
                HStack {
                    Label("Camera and output changes apply after a restart.", systemImage: "arrow.triangle.2.circlepath")
                        .font(.caption).foregroundStyle(.orange)
                    Spacer()
                    Button("Restart camera", action: model.restart).disabled(model.state == "stopping")
                }
            }
            Text(model.active ? "Effects apply live while the camera runs." : "Choose settings, then start camera to preview.")
                .font(.caption).foregroundStyle(.secondary)
            if !model.connected && !model.hasWorker {
                Button("Reconnect worker", action: model.reconnect)
            }
            HStack {
                Button(model.active ? "Stop camera" : "Start camera", action: model.active ? model.stop : model.start)
                    .buttonStyle(.borderedProminent).disabled(!model.connected || model.state == "stopping" || (!model.active && (model.cameraUnavailable || model.outputUnavailable)))
                if model.state == "running" {
                    Button(model.paused ? "Resume video" : "Pause video", action: model.togglePause)
                        .help("Control-Option-P from any app")
                }
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
        .onChange(of: model.config.effect) { _ in model.prepareImageBackground() }
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

    private func decimalSlider(_ title: String, value: Binding<Double>, range: ClosedRange<Double>, text: (Double) -> String) -> some View {
        HStack {
            Text(title).frame(width: 75, alignment: .leading)
            // two decimals keep saved profiles readable and live updates sparse
            Slider(value: Binding(get: { value.wrappedValue }, set: { value.wrappedValue = ($0 * 100).rounded() / 100 }), in: range)
            Text(text(value.wrappedValue)).monospacedDigit().frame(width: 44, alignment: .trailing)
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

struct BackgroundGallery: View {
    @ObservedObject var model: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Quiet spaces for work calls.").font(.caption).foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 135), spacing: 10)], spacing: 10) {
                ForEach(BuiltInBackground.catalog) { background in
                    let selected = model.selectedBackground?.id == background.id
                    Button { model.selectBackground(background) } label: {
                        VStack(alignment: .leading, spacing: 5) {
                            Image(nsImage: background.image).resizable().scaledToFit()
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                                .overlay(alignment: .topTrailing) {
                                    if selected {
                                        Image(systemName: "checkmark.circle.fill")
                                            .foregroundStyle(.white, Color.accentColor)
                                            .padding(5)
                                    }
                                }
                            Text(background.title).font(.caption).foregroundStyle(.primary)
                        }.padding(5)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(selected ? Color.accentColor.opacity(0.1) : Color.clear)
                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Color.accentColor : Color.secondary.opacity(0.25), lineWidth: selected ? 2 : 1))
                            .contentShape(RoundedRectangle(cornerRadius: 8))
                    }.buttonStyle(.plain)
                        .accessibilityLabel(background.title)
                        .accessibilityAddTraits(selected ? [.isSelected] : [])
                }
            }
            HStack {
                Text(model.selectedBackground?.title ?? (model.config.image_path.isEmpty ? "Choose a background" : URL(fileURLWithPath: model.config.image_path).lastPathComponent))
                    .font(.caption).lineLimit(1).truncationMode(.middle)
                Spacer()
                Button("Choose your own...", action: model.chooseImage)
            }
        }
    }
}

struct PreviewPanel: View {
    @ObservedObject var model: SessionModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // narrow windows move the view controls below the title
            ViewThatFits(in: .horizontal) {
                HStack {
                    title
                    Spacer()
                    viewControls
                    destination
                }
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        title
                        Spacer()
                        destination
                    }
                    HStack { viewControls }
                }
            }
            ZStack {
                Color.black
                if let image = model.previewImage {
                    Image(nsImage: image).resizable().scaledToFit()
                        .overlay {
                            // the app draws its own crop so dragging needs no round trip
                            GuideOverlay(guides: model.previewGuides.filter { $0.key != "crop" })
                            if model.pickingWhite {
                                WhitePicker(model: model)
                            } else if model.previewView == "source" {
                                CropEditor(model: model)
                            }
                        }
                        .overlay(alignment: .topLeading) {
                            if model.comparing {
                                Text("Original").font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 3)
                                    .background(Capsule().fill(.black.opacity(0.6))).foregroundStyle(.white).padding(8)
                            }
                        }
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
                .accessibilityLabel(model.previewView == "output" ? "Processed video preview" : model.previewView == "source" ? "Camera preview" : "Segmentation mask preview")
            if let error = model.previewError {
                Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
            }
            Text(caption).font(.caption).foregroundStyle(.secondary)
            if let stats = model.stats {
                Text(stats.summary).font(.caption).monospacedDigit().foregroundStyle(.secondary)
            }
        }.padding(20).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

extension PreviewPanel {
    var title: some View { Text("Video preview").font(.headline).lineLimit(1) }

    var destination: some View {
        Text(model.outputMode == "preview" ? "Preview only" : "OBS Virtual Camera")
            .font(.caption).foregroundStyle(.secondary).lineLimit(1)
    }

    @ViewBuilder var viewControls: some View {
        Picker("View", selection: $model.previewView) {
            Text("Output").tag("output")
            Text("Camera").tag("source")
            if model.maskAvailable { Text("Mask").tag("mask") }
        }.pickerStyle(.segmented).labelsHidden().fixedSize()
            .help("Output: what calls receive. Camera: full camera picture before framing and effects. Mask: what background effects keep.")
        if model.previewView == "output" && model.previewing { CompareButton(model: model).fixedSize() }
    }

    var caption: String {
        if model.paused { return "Paused: calls see the loading picture and the camera is off." }
        switch model.previewView {
        case "source" where model.pickingWhite:
            return "Click something white or gray to balance color."
        case "source":
            return model.previewGuides.isEmpty
                ? "Camera view shows the full picture before framing and effects."
                : "Camera view: yellow box is the detected face, green dashes are auto framing."
        case "mask":
            return "Mask view: white is kept as you, black gets the background effect."
        default:
            return model.comparing
                ? "Original: same framing without background or image effects. Release to see the output."
                : "Preview shows final framing and effects at the output frame rate."
        }
    }
}

struct WhitePicker: View {
    @ObservedObject var model: SessionModel

    var body: some View {
        GeometryReader { geometry in
            Color.clear.contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onEnded { value in
                    let size = geometry.size
                    model.pickWhite(at: CGPoint(x: value.location.x / max(size.width, 1), y: value.location.y / max(size.height, 1)))
                })
                .onHover { inside in inside ? NSCursor.crosshair.push() : NSCursor.pop() }
                .overlay(alignment: .topTrailing) {
                    Button("Cancel", action: model.cancelWhitePick).padding(8)
                }
                .accessibilityLabel("Camera picture")
                .accessibilityHint("Click something white or gray to balance color")
        }
    }
}

// press and hold; VoiceOver toggles instead
struct CompareButton: View {
    @ObservedObject var model: SessionModel

    var body: some View {
        Label("Compare", systemImage: "square.split.2x1")
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(RoundedRectangle(cornerRadius: 6).fill(model.comparing ? Color.accentColor.opacity(0.4) : Color.secondary.opacity(0.15)))
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in if !model.comparing { model.comparing = true } }
                .onEnded { _ in model.comparing = false })
            .help("Hold to see the same framing without background or image effects.")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { model.comparing.toggle() }
    }
}

struct GuideOverlay: View {
    let guides: [String: CGRect]

    var body: some View {
        GeometryReader { geometry in
            ForEach(guides.keys.sorted(), id: \.self) { name in
                let box = guides[name] ?? .zero
                let size = geometry.size
                Path(CGRect(x: box.minX * size.width, y: box.minY * size.height, width: box.width * size.width, height: box.height * size.height))
                    .stroke(Self.color(name), style: StrokeStyle(lineWidth: 2, dash: name == "framing" ? [6, 4] : []))
            }
        }.allowsHitTesting(false)
    }

    static func color(_ name: String) -> Color {
        switch name {
        case "face": return .yellow
        case "framing": return .green
        default: return .white
        }
    }
}

struct CropEditor: View {
    @ObservedObject var model: SessionModel
    @State private var dragStart: CGPoint?
    @State private var zoomStart: Double?

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            if let crop = model.config.crop, crop.count == 4 {
                let box = CGRect(x: crop[0] * size.width, y: crop[1] * size.height, width: crop[2] * size.width, height: crop[3] * size.height)
                Path { path in
                    // dim everything calls will not see
                    path.addRect(CGRect(x: 0, y: 0, width: size.width, height: box.minY))
                    path.addRect(CGRect(x: 0, y: box.maxY, width: size.width, height: size.height - box.maxY))
                    path.addRect(CGRect(x: 0, y: box.minY, width: box.minX, height: box.height))
                    path.addRect(CGRect(x: box.maxX, y: box.minY, width: size.width - box.maxX, height: box.height))
                }.fill(Color.black.opacity(0.5))
                Path(box).stroke(Color.white, lineWidth: 2)
                Color.clear.contentShape(Rectangle())
                    .gesture(DragGesture(minimumDistance: 1).onChanged { value in
                        let start = dragStart ?? model.config.cropCenter
                        dragStart = start
                        model.config.setCrop(zoom: model.config.cropZoom, center: CGPoint(
                            x: start.x + value.translation.width / max(size.width, 1),
                            y: start.y + value.translation.height / max(size.height, 1)))
                    }.onEnded { _ in dragStart = nil })
                    .simultaneousGesture(MagnificationGesture().onChanged { scale in
                        let start = zoomStart ?? model.config.cropZoom
                        zoomStart = start
                        model.config.setCrop(zoom: start * scale, center: model.config.cropCenter)
                    }.onEnded { _ in zoomStart = nil })
                    .accessibilityLabel("Crop area")
                    .accessibilityHint("Drag to move what calls see")
            }
        }
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
        let arguments = CommandLine.arguments
        if let index = arguments.firstIndex(of: "--snapshot"), index + 1 < arguments.count {
            let image = index + 2 < arguments.count ? NSImage(contentsOfFile: arguments[index + 2]) : nil
            do { try MainActor.assumeIsolated { try SessionModel.renderSnapshots(to: URL(fileURLWithPath: arguments[index + 1]), image: image) }; exit(0) }
            catch {
                FileHandle.standardError.write(Data("Snapshot failed: \(error.localizedDescription)\n".utf8))
                exit(1)
            }
        }
        if CommandLine.arguments.contains("--self-test") {
            do { try SessionModel.selfTest(); exit(0) }
            catch {
                FileHandle.standardError.write(Data("Native model self-test failed: \(error.localizedDescription)\n".utf8))
                exit(1)
            }
        }
    }
    var body: some Scene {
        MenuBarExtra("Webcam Mods", systemImage: model.paused ? "video.slash" : model.state == "running" ? "video.fill" : "video") {
            Text("Camera: \(model.paused ? "Paused" : model.state.capitalized)")
            Button(model.active ? "Stop camera" : "Start camera", action: model.active ? model.stop : model.start)
                .disabled(!model.connected || model.state == "stopping" || (!model.active && (model.cameraUnavailable || model.outputUnavailable)))
            Button(model.paused ? "Resume video" : "Pause video", action: model.togglePause)
                .keyboardShortcut("p", modifiers: [.control, .option])
                .disabled(model.state != "running")
            if !model.profiles.isEmpty {
                Picker("Profile", selection: Binding(get: { model.selectedProfile }, set: model.switchProfile)) {
                    ForEach(model.profiles) { profile in Text(profile.name).tag(profile.name) }
                }.disabled(!model.connected || model.state == "stopping")
            }
            Button("Open window") { delegate.showControls() }.keyboardShortcut("o")
            Divider()
            Button("Quit Webcam Mods", action: model.quit).keyboardShortcut("q")
        }
    }
}

// Control-Option-P toggles pause from any app; Carbon hot keys need no
// accessibility permission and only fire for this exact combination
enum PauseHotKey {
    private static var hotKey: EventHotKeyRef?

    static func register() {
        guard hotKey == nil else { return }
        var pressed = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let installed = InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            Task { @MainActor in SessionModel.current?.togglePause() }
            return noErr
        }, 1, &pressed, nil, nil)
        // 'WCMP'
        let id = EventHotKeyID(signature: 0x5743_4D50, id: 1)
        let status = installed == noErr
            ? RegisterEventHotKey(UInt32(kVK_ANSI_P), UInt32(controlKey | optionKey), id, GetApplicationEventTarget(), 0, &hotKey)
            : installed
        if status != noErr {
            FileHandle.standardError.write(Data("Pause shortcut Control-Option-P unavailable (\(status)); use the menu bar.\n".utf8))
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var controlsWindow: NSWindow?
    private var previewTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        showControls()
        schedulePreview()
        PauseHotKey.register()
    }

    private func schedulePreview() {
        let timer = Timer(timeInterval: SessionModel.current?.previewInterval ?? 1 / Configuration().fps, repeats: true) { [weak self] timer in
            Task { @MainActor in
                guard let self else { return }
                let visible = self.controlsWindow.map { $0.isVisible && !$0.isMiniaturized } ?? false
                SessionModel.current?.pollPreview(visible: visible)
                SessionModel.current?.pollStats(visible: visible)
                if let model = SessionModel.current, timer.timeInterval != model.previewInterval {
                    timer.invalidate()
                    self.schedulePreview()
                }
            }
        }
        previewTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        SessionModel.current?.refreshOBS()
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
