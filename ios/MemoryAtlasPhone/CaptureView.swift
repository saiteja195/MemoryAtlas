import SwiftUI
import MemoryAtlasCore

struct CaptureView: View {
    @Bindable var glasses: GlassesCapture
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("gatewayURL") private var gatewayURL = ""
    @State private var token = TokenStore.read()
    @State private var consent = false
    @State private var connected = false
    @State private var busy = false
    @State private var message: String?
    @State private var failure: String?
    @State private var uploadTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                Section("1 · Connect to your Mac") {
                    TextField("http://your-mac.local:8001", text: $gatewayURL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    SecureField("Phone access token", text: $token)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button(connected ? "Connection verified · check again" : "Check connection & save token") {
                        run { client in
                            try await client.checkConnection()
                            try TokenStore.save(token.trimmingCharacters(in: .whitespacesAndNewlines))
                            connected = true
                            message = "Live backend ready. The model key stays on your Mac."
                        }
                    }.disabled(busy)
                    Text("Use your Mac’s address, not localhost. HTTP is for trusted local Wi-Fi only; use HTTPS elsewhere.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("2 · Oakley HSTN") {
                    Label(glasses.status, systemImage: "eyeglasses")
                    if !glasses.registered {
                        Button("Connect glasses in Meta AI") { Task { await glasses.connect() } }
                            .disabled(!glasses.sdkReady)
                    }
                    Button("Start glasses session") { glasses.startSession() }.disabled(!glasses.canStart)
                    Button("Allow camera & start") { Task { await glasses.startCamera() } }
                        .disabled(glasses.sessionState != .started || glasses.streamState != .stopped)
                    Button(glasses.capturing ? "Waiting for glasses photo…" : "Capture photo from glasses") {
                        message = nil
                        glasses.capture()
                    }.disabled(!glasses.canCapture || busy)
                    Button("Stop session", role: .destructive) { glasses.stop() }
                    Text("Wear the glasses. Camera permission may open Meta AI. No audio is recorded.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if let bytes = glasses.photo, let image = UIImage(data: bytes) {
                    Section("3 · Review this photo") {
                        Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 260)
                            .accessibilityLabel("Photo captured by your glasses")
                        Toggle("Allow this photo to be processed by my backend and Meta", isOn: $consent)
                        Button(busy ? "Creating memory…" : "Send photo to MemoryAtlas") { upload(bytes) }
                            .disabled(!connected || !consent || busy)
                        Button("Discard photo", role: .destructive) { glasses.discard() }.disabled(busy)
                        Text("The photo stays in memory until you send or discard it. It is not saved to Photos. Sending creates a consent grant and a text memory.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if busy { ProgressView("Working… keep the app open") }
                if let message { Section("Result") { Text(message).textSelection(.enabled) } }
                if let failure = failure ?? glasses.error {
                    Section("Needs attention") { Text(failure).foregroundStyle(.red).textSelection(.enabled) }
                }
            }
            .navigationTitle("MemoryAtlas Capture")
            .disabled(busy && scenePhase != .active)
            .onChange(of: gatewayURL) { _, _ in connected = false }
            .onChange(of: token) { _, _ in connected = false }
            .onChange(of: glasses.photo) { _, _ in consent = false }
            .onChange(of: scenePhase) { _, phase in
                if phase == .background {
                    uploadTask?.cancel()
                    busy = false
                    glasses.background()
                }
            }
        }
    }

    private func run(_ action: @escaping @MainActor (AtlasClient) async throws -> Void) {
        busy = true
        failure = nil
        glasses.error = nil
        uploadTask = Task { @MainActor in
            defer { busy = false }
            do {
                let client = try AtlasClient(baseURL: gatewayURL, token: token)
                try await action(client)
            } catch is CancellationError {
                failure = "Request cancelled. If you were uploading, check the graph before trying again."
            } catch { failure = error.localizedDescription }
        }
    }

    private func upload(_ bytes: Data) {
        guard consent, let at = glasses.capturedAt else { return }
        run { client in
            try await client.checkConnection()
            let session = try await client.startSession()
            let result = try await client.upload(jpeg: bytes, capturedAt: at, sessionID: session.sessionID)
            try Task.checkCancellation()
            message = "Memory stored · \(result.claims) claims\n\(result.observation)\nSource: \(result.sourceID)\nOpen the Atlas on your Mac to see the new photo’s claims."
            glasses.discard()
        }
    }
}
