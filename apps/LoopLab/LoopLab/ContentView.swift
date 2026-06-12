import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        TabView {
            NavigationStack {
                List {
                    Section("Account") {
                        Text(model.account.displayName)
                            .accessibilityIdentifier("account-name")
                        Text(model.account.banner)
                            .accessibilityIdentifier("account-banner")
                        Toggle("Logged in", isOn: $model.loggedIn)
                            .accessibilityIdentifier("logged-in-toggle")
                    }

                    Section("Records") {
                        if model.account.records.isEmpty {
                            Text("No records")
                                .accessibilityIdentifier("empty-records")
                        } else {
                            ForEach(model.account.records, id: \.self) { record in
                                NavigationLink(record) {
                                    RecordDetail(record: record)
                                }
                                .accessibilityIdentifier("record-\(record)")
                            }
                        }
                    }
                }
                .navigationTitle("LoopLab")
                .toolbar {
                    Button("Reload") {
                        Task { await model.loadAccount() }
                    }
                    .accessibilityIdentifier("reload-account")
                }
            }
            .tabItem { Label("Data", systemImage: "list.bullet") }

            CameraSurface()
                .tabItem { Label("Camera", systemImage: "camera") }

            SettingsView()
                .tabItem { Label("Settings", systemImage: "gear") }
        }
        .task {
            model.refreshCameraPermission()
            await model.loadAccount()
        }
    }
}

struct RecordDetail: View {
    @EnvironmentObject private var model: AppModel
    let record: String

    var body: some View {
        VStack(spacing: 16) {
            Text(record)
                .font(.title)
                .accessibilityIdentifier("record-detail-title")
            Text("Deep link target: \(model.deepLinkTarget)")
                .accessibilityIdentifier("deep-link-target")
            Button("Select") {
                model.selectedRecord = record
            }
            .accessibilityIdentifier("select-record")
        }
        .padding()
        .navigationTitle("Detail")
    }
}

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        Form {
            Section("Experiment") {
                Text("Settings label v1")
                    .accessibilityIdentifier("settings-label")
                Text("Status: \(model.status)")
                    .accessibilityIdentifier("status")
                Button("Reset local state") {
                    model.resetLocalState()
                }
                .accessibilityIdentifier("reset-local-state")
            }

            Section("Permission") {
                Text("Camera permission: \(model.cameraPermission)")
                    .accessibilityIdentifier("camera-permission")
                Button("Request camera permission") {
                    model.requestCameraPermission()
                }
                .accessibilityIdentifier("request-camera-permission")
            }
        }
    }
}
