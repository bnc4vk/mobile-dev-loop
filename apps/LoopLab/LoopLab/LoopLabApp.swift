import SwiftUI

@main
struct LoopLabApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onOpenURL { url in
                    model.handleDeepLink(url)
                }
        }
    }
}
