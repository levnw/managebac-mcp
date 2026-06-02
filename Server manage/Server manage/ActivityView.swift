import SwiftUI

struct ActivityRow: View {
    let item: ActivityItem
    let showUser: Bool
    let emailFor: (String) -> String
    init(_ item: ActivityItem, showUser: Bool, emailFor: @escaping (String) -> String) {
        self.item = item; self.showUser = showUser; self.emailFor = emailFor
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text(item.tool).font(.rowTitle).foregroundStyle(Theme.text)
                Spacer()
                Text(timeAgo(item.ts)).font(.rowMeta).foregroundStyle(Theme.faint)
            }
            let line = [showUser ? emailFor(item.user_id) : "", item.argsSummary]
                .filter { !$0.isEmpty }.joined(separator: "  ·  ")
            if !line.isEmpty {
                Text(line).font(.rowMeta).foregroundStyle(Theme.secondary).padding(.top, 3)
            }
        }
        .padding(.vertical, 12)
        .overlay(alignment: .bottom) { Divider().overlay(Theme.hairline) }
    }
}

struct ActivityView: View {
    @EnvironmentObject var session: Session
    @State private var items: [ActivityItem] = []
    @State private var emails: [String: String] = [:]
    @State private var error = ""
    @State private var loading = false

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                if !error.isEmpty { EmptyHint(text: error) }
                else if items.isEmpty && !loading { EmptyHint(text: "No activity yet.") }
                ForEach(items) { ActivityRow($0, showUser: true, emailFor: { emails[$0] ?? "unknown" }) }
            }
            .padding(.horizontal, 24).padding(.top, 8)
        }
        .background(Theme.bg)
        .refreshable { await load() }
        .task { await load() }
    }

    private func load() async {
        loading = true; error = ""
        do {
            let api = API(session)
            async let a = api.activity()
            async let u = api.users()
            items = try await a
            emails = Dictionary(uniqueKeysWithValues: try await u.map { ($0.id, $0.email) })
        } catch let err { error = err.localizedDescription }
        loading = false
    }
}
