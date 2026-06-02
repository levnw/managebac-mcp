import SwiftUI

struct OverviewView: View {
    @EnvironmentObject var session: Session
    @State private var users: [AdminUser] = []
    @State private var codes: [InviteCode] = []
    @State private var error = ""
    @State private var loading = false

    private var activeToday: Int {
        let dayAgo = Int(Date().timeIntervalSince1970) - 86400
        return users.filter { ($0.last_active ?? 0) >= dayAgo }.count
    }
    private var totalCalls: Int { users.reduce(0) { $0 + $1.request_count } }
    private var pendingCount: Int { users.filter { !$0.approved }.count }
    private var pausedCount: Int { users.filter { !$0.enabled }.count }
    private var unusedCodes: Int { codes.filter { !$0.used }.count }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if !error.isEmpty { EmptyHint(text: error) }

                stat("People connected", "\(users.count)")
                stat("Awaiting approval", "\(pendingCount)")
                stat("Active in last 24h", "\(activeToday)")
                stat("Paused", "\(pausedCount)")
                stat("Total tool calls", "\(totalCalls)")
                stat("Unused invite codes", "\(unusedCodes)")
            }
            .padding(.horizontal, 24).padding(.top, 14)
        }
        .background(Theme.bg)
        .refreshable { await load() }
        .task { await load() }
    }

    private func stat(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(.rowTitle).foregroundStyle(Theme.text)
            Spacer()
            Text(value).font(.system(size: 22, weight: .semibold)).foregroundStyle(Theme.text)
        }
        .padding(.horizontal, 16).padding(.vertical, 16)
        .background(Card { Color.clear })
    }

    private func load() async {
        loading = true; error = ""
        do {
            let api = API(session)
            async let u = api.users()
            async let c = api.codes()
            users = try await u
            codes = try await c
        } catch let err { error = err.localizedDescription }
        loading = false
    }
}
