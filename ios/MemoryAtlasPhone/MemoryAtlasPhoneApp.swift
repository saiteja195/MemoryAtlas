import SwiftUI

@main @MainActor
struct MemoryAtlasPhoneApp: App {
    @State private var glasses = GlassesCapture()
    var body: some Scene {
        WindowGroup {
            CaptureView(glasses: glasses)
                .onOpenURL { url in Task { await glasses.handleCallback(url) } }
        }
    }
}
