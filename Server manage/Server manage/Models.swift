import Foundation

struct LoginResponse: Codable {
    let token: String
    let expires_at: Int
}

struct AdminUser: Codable, Identifiable, Hashable {
    let id: String
    let label: String
    let mb_url: String
    let email: String
    let created_at: Int
    let request_count: Int
    let last_active: Int?
    let token: String
    let enabled: Bool
}

struct InviteCode: Codable, Identifiable, Hashable {
    var id: String { code }
    let code: String
    let note: String
    let created_at: Int
    let used: Bool
    let used_email: String?
    let used_at: Int?
}

struct ActivityItem: Decodable, Identifiable, Hashable {
    var id: String { "\(ts)-\(tool)-\(user_id)" }
    let ts: Int
    let user_id: String
    let tool: String
    let duration_ms: Int
    // args is free-form; we render a short summary, so decode leniently
    let argsSummary: String

    enum CodingKeys: String, CodingKey { case ts, user_id, tool, duration_ms, args }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ts = try c.decode(Int.self, forKey: .ts)
        user_id = try c.decode(String.self, forKey: .user_id)
        tool = try c.decode(String.self, forKey: .tool)
        duration_ms = (try? c.decode(Int.self, forKey: .duration_ms)) ?? 0
        if let dict = try? c.decode([String: JSONValue].self, forKey: .args), !dict.isEmpty {
            argsSummary = dict.map { "\($0.key): \($0.value.short)" }.sorted().joined(separator: ", ")
        } else {
            argsSummary = ""
        }
    }
}

// Tiny JSON value to summarize arbitrary tool args.
enum JSONValue: Codable {
    case string(String), int(Int), double(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Int.self) { self = .int(v) }
        else if let v = try? c.decode(Double.self) { self = .double(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else if let v = try? c.decode([String: JSONValue].self) { self = .object(v) }
        else { self = .null }
    }
    func encode(to encoder: Encoder) throws {}
    var short: String {
        switch self {
        case .string(let s): return s
        case .int(let i): return String(i)
        case .double(let d): return String(d)
        case .bool(let b): return String(b)
        case .array(let a): return "[\(a.count)]"
        case .object: return "{…}"
        case .null: return "—"
        }
    }
}

struct CodesResponse: Codable { let codes: [InviteCode] }
struct UsersResponse: Codable { let users: [AdminUser] }
struct ActivityResponse: Decodable { let activity: [ActivityItem] }
