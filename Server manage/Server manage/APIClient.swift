import Foundation
import SwiftUI
import Combine

@MainActor
final class Session: ObservableObject {
    @Published var baseURL: String = UserDefaults.standard.string(forKey: "baseURL") ?? "https://managebac.822538.xyz"
    @Published var username: String = UserDefaults.standard.string(forKey: "username") ?? ""
    @Published private(set) var token: String? = Keychain.read("adminToken")
    @Published var loggedIn: Bool = Keychain.read("adminToken") != nil

    func persistField() {
        UserDefaults.standard.set(baseURL, forKey: "baseURL")
        UserDefaults.standard.set(username, forKey: "username")
    }

    func setToken(_ t: String) {
        Keychain.save("adminToken", t)
        token = t
        loggedIn = true
        persistField()
    }

    func logout() {
        Keychain.delete("adminToken")
        token = nil
        loggedIn = false
    }
}

enum APIError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let m) = self { return m }; return "Error" }
}

@MainActor
final class API {
    let session: Session
    init(_ session: Session) { self.session = session }

    private func url(_ path: String) throws -> URL {
        let base = session.baseURL.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let u = URL(string: base + path) else { throw APIError.message("Invalid server URL") }
        return u
    }

    private func request(_ path: String, method: String = "GET", body: [String: Any]? = nil, auth: Bool = true) async throws -> Data {
        var req = URLRequest(url: try url(path))
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let t = session.token { req.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization") }
        if let body { req.httpBody = try JSONSerialization.data(withJSONObject: body) }
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw APIError.message("No response") }
        if http.statusCode == 401 {
            if auth { session.logout() }
            throw APIError.message("Unauthorized")
        }
        guard (200..<300).contains(http.statusCode) else {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["error"] as? String
            throw APIError.message(msg ?? "Server error (\(http.statusCode))")
        }
        return data
    }

    func login(username: String, password: String) async throws {
        let data = try await request("/admin/login", method: "POST",
                                     body: ["username": username, "password": password], auth: false)
        let r = try JSONDecoder().decode(LoginResponse.self, from: data)
        session.username = username
        session.setToken(r.token)
    }

    func users() async throws -> [AdminUser] {
        try JSONDecoder().decode(UsersResponse.self, from: await request("/admin/users")).users
    }
    func deleteUser(_ id: String) async throws {
        _ = try await request("/admin/users/\(id)", method: "DELETE")
    }
    func userActivity(_ id: String) async throws -> [ActivityItem] {
        try JSONDecoder().decode(ActivityResponse.self, from: await request("/admin/users/\(id)/activity")).activity
    }
    func activity() async throws -> [ActivityItem] {
        try JSONDecoder().decode(ActivityResponse.self, from: await request("/admin/activity")).activity
    }
    func codes() async throws -> [InviteCode] {
        try JSONDecoder().decode(CodesResponse.self, from: await request("/admin/codes")).codes
    }
    func createCode(note: String) async throws -> InviteCode {
        try JSONDecoder().decode(InviteCode.self, from: await request("/admin/codes", method: "POST", body: ["note": note]))
    }
    func deleteCode(_ code: String) async throws {
        _ = try await request("/admin/codes/\(code)", method: "DELETE")
    }
}
