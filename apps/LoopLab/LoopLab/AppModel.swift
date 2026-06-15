import AVFoundation
import Foundation
import SwiftUI

struct AccountState: Codable, Equatable {
    var accountID: String
    var displayName: String
    var records: [String]
    var banner: String
    var shouldCrash: Bool
}

@MainActor
final class AppModel: ObservableObject {
    private let legacyLoggedInStorageKey = "loggedIn"

    @Published var account = AccountState(accountID: "unknown", displayName: "Unknown", records: [], banner: "Not loaded", shouldCrash: false)
    @Published var selectedRecord: String?
    @Published var status = "Ready"
    @Published var deepLinkTarget = "none"
    @Published var cameraPermission = "unknown"
    @Published var cameraSurfaceLabel = "Camera surface ready"
    @AppStorage("isLoggedIn") var loggedIn = false

    private let session = URLSession.shared

    var backendBaseURL: URL {
        if let arg = ProcessInfo.processInfo.arguments.first(where: { $0.hasPrefix("--backend-url=") }) {
            return URL(string: String(arg.dropFirst("--backend-url=".count)))!
        }
        return URL(string: "http://127.0.0.1:8765")!
    }

    func loadAccount() async {
        do {
            let url = backendBaseURL.appendingPathComponent("account")
            let (data, _) = try await session.data(from: url)
            let decoded = try JSONDecoder().decode(AccountState.self, from: data)
            if decoded.shouldCrash {
                status = "Fixture requested crash path"
                fatalError("Injected crash from backend fixture")
            }
            account = decoded
            status = "Loaded \(decoded.accountID)"
        } catch {
            status = "Backend error: \(error.localizedDescription)"
        }
    }

    func refreshCameraPermission() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            cameraPermission = "authorized"
        case .denied:
            cameraPermission = "denied"
        case .restricted:
            cameraPermission = "restricted"
        case .notDetermined:
            cameraPermission = "notDetermined"
        @unknown default:
            cameraPermission = "unknown"
        }
    }

    func requestCameraPermission() {
        AVCaptureDevice.requestAccess(for: .video) { [weak self] _ in
            Task { @MainActor in
                self?.refreshCameraPermission()
            }
        }
    }

    func handleDeepLink(_ url: URL) {
        deepLinkTarget = url.absoluteString
        if url.host == "record", let record = url.pathComponents.dropFirst().first {
            selectedRecord = record
        }
    }

    func resetLocalState() {
        loggedIn = false
        selectedRecord = nil
        deepLinkTarget = "none"
        status = "Local state reset"
    }
}
