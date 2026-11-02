import Foundation
import Observation
import UIKit
import MWDATCore
import MWDATCamera

/// User-triggered photos only. No camera-roll writes, audio, automatic upload or background capture.
@Observable @MainActor
final class GlassesCapture {
    var registered = false
    var deviceAvailable = false
    var sessionState: DeviceSessionState = .idle
    var streamState: StreamState = .stopped
    var photo: Data?
    var capturedAt: Date?
    var capturing = false
    var error: String?
    var sdkReady = false

    @ObservationIgnored private var wearables: (any WearablesInterface)?
    @ObservationIgnored private var selector: AutoDeviceSelector?
    @ObservationIgnored private var session: DeviceSession?
    @ObservationIgnored private var camera: MWDATCamera.Camera?
    @ObservationIgnored private let sessionTokens = ListenerTokenBag()
    @ObservationIgnored private let cameraTokens = ListenerTokenBag()
    @ObservationIgnored private var registrationTask: Task<Void, Never>?
    @ObservationIgnored private var deviceTask: Task<Void, Never>?
    @ObservationIgnored private var captureTimeout: Task<Void, Never>?

    var canStart: Bool { sdkReady && registered && deviceAvailable && session == nil }
    var canCapture: Bool { streamState == .streaming && !capturing && photo == nil }
    var status: String {
        if streamState == .streaming { return "Glasses camera ready" }
        if sessionState == .started { return "Session connected · start camera" }
        if sessionState == .starting { return "Connecting to glasses…" }
        if !registered { return "Connect through Meta AI" }
        return deviceAvailable ? "HSTN available" : "Put on your glasses and open Meta AI"
    }

    init() {
        do {
            try Wearables.configure()
            let sdk = Wearables.shared
            wearables = sdk
            let deviceSelector = AutoDeviceSelector(wearables: sdk)
            selector = deviceSelector
            registered = sdk.registrationState == .registered
            sdkReady = true
            registrationTask = Task { [weak self] in
                for await state in sdk.registrationStateStream() {
                    guard let self, !Task.isCancelled else { return }
                    self.registered = state == .registered
                    if !self.registered { self.stop() }
                }
            }
            deviceTask = Task { [weak self] in
                for await device in deviceSelector.activeDeviceStream() {
                    guard let self, !Task.isCancelled else { return }
                    self.deviceAvailable = device != nil
                    if device == nil { self.stop() }
                }
            }
        } catch {
            self.error = "Wearables SDK setup failed: \(error.localizedDescription)"
        }
    }

    isolated deinit {
        registrationTask?.cancel()
        deviceTask?.cancel()
        captureTimeout?.cancel()
        session?.stop()
    }

    func connect() async {
        guard let wearables else { return }
        do { try await wearables.startRegistration() }
        catch { self.error = error.localizedDescription }
    }

    func handleCallback(_ url: URL) async {
        guard url.scheme == "memoryatlas", let wearables,
              URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
                .contains(where: { $0.name == "metaWearablesAction" }) == true else { return }
        do { _ = try await wearables.handleUrl(url) }
        catch { self.error = error.localizedDescription }
    }

    func startSession() {
        guard canStart, let wearables, let selector else { return }
        do {
            let newSession = try wearables.createSession(deviceSelector: selector)
            session = newSession
            newSession.statePublisher.listen { [weak self] state in
                Task { @MainActor in
                    self?.sessionState = state
                    if state == .stopped { self?.stop() }
                }
            }.store(in: sessionTokens)
            newSession.errorPublisher.listen { [weak self] error in
                let message = error.localizedDescription
                Task { @MainActor in self?.error = message; self?.stop() }
            }.store(in: sessionTokens)
            sessionState = .starting
            try newSession.start()
        } catch {
            self.error = error.localizedDescription
            stop()
        }
    }

    /// This explicit user action may switch to Meta AI to request camera permission.
    func startCamera() async {
        guard let wearables, let session, sessionState == .started, camera == nil else { return }
        do {
            var permission = try await wearables.checkPermissionStatus(.camera)
            if permission != .granted { permission = try await wearables.requestPermission(.camera) }
            guard permission == .granted else { error = "Camera permission was not granted in Meta AI."; return }
            guard self.session === session, sessionState == .started else { return }
            let configuration = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 24)
            guard let camera = try session.addCamera(config: configuration) else {
                error = "Camera unavailable. Stop and start the session again."
                return
            }
            self.camera = camera
            let stream = camera.stream
            stream.statePublisher.listen { [weak self] state in
                Task { @MainActor in
                    self?.streamState = state
                    if state == .stopped { self?.clearCamera() }
                }
            }.store(in: cameraTokens)
            stream.errorPublisher.listen { [weak self] error in
                let message = error.localizedDescription
                Task { @MainActor in self?.error = message; self?.clearCamera() }
            }.store(in: cameraTokens)
            stream.photoDataPublisher.listen { [weak self] data in
                let bytes = data.data
                Task { @MainActor in self?.receive(bytes) }
            }.store(in: cameraTokens)
            streamState = .starting
            stream.start()
        } catch { self.error = error.localizedDescription }
    }

    func capture() {
        guard canCapture, let camera else { return }
        capturing = true
        capturedAt = Date()
        guard camera.stream.capturePhoto(format: .jpeg) else {
            capturing = false
            error = "The glasses did not start photo capture. Try again."
            return
        }
        captureTimeout = Task { [weak self] in
            try? await Task.sleep(for: .seconds(15))
            guard !Task.isCancelled, let self, self.capturing else { return }
            self.capturing = false
            self.error = "No photo arrived from the glasses. Stop the session and reconnect."
        }
    }

    private func receive(_ bytes: Data) {
        guard capturing else { return }
        captureTimeout?.cancel()
        capturing = false
        guard let image = UIImage(data: bytes) else { error = "The glasses returned an unreadable photo."; return }
        // Strip metadata and bound upload size; retain only the review image in RAM.
        let scale = min(1, 1600 / max(image.size.width, image.size.height))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
        guard let jpeg = resized.jpegData(compressionQuality: 0.75), jpeg.count <= 2 * 1024 * 1024 else {
            error = "Photo is too large after resizing. Please capture again."
            return
        }
        photo = jpeg
        clearCamera()
    }

    func discard() {
        photo = nil
        capturedAt = nil
        capturing = false
        captureTimeout?.cancel()
    }

    private func clearCamera() {
        cameraTokens.clear()
        camera?.stop()
        camera = nil
        streamState = .stopped
        capturing = false
        captureTimeout?.cancel()
    }

    func stop() {
        clearCamera()
        sessionTokens.clear()
        session?.stop()
        session = nil
        sessionState = .stopped
        discard()
    }

    func background() {
        // Do not tear down a session awaiting the Meta AI camera-permission callback.
        if camera != nil || photo != nil { stop() }
    }
}
