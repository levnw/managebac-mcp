import SwiftUI

@main
struct ServerManageApp: App {
    @StateObject private var session = Session()

    var body: some Scene {
        WindowGroup {
            Group {
                if session.loggedIn {
                    RootView()
                } else {
                    LoginView()
                }
            }
            .environmentObject(session)
            .tint(Theme.accent)
        }
        #if os(macOS)
        .defaultSize(width: 880, height: 620)
        #endif
    }
}
