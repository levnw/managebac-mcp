import SwiftUI

struct UsersView: View {
    @EnvironmentObject var session: Session
    @State private var state = LoadState<AdminUser>()

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 0) {
                    if !state.error.isEmpty { EmptyHint(text: state.error) }
                    else if state.items.isEmpty && !state.loading {
                        EmptyHint(text: "No one has connected yet. Share an invite code from the Invite codes tab.")
                    }
                    ForEach(state.items) { user in
                        NavigationLink(value: user) { row(user) }
                            .buttonStyle(.plain)
                        Divider().overlay(Theme.hairline)
                    }
                }
                .padding(.horizontal, 24).padding(.top, 8)
            }
            .background(Theme.bg)
            .navigationDestination(for: AdminUser.self) { UserDetailView(user: $0, onRemoved: { Task { await load() } }) }
            .refreshable { await load() }
        }
        .task { await load() }
    }

    private func row(_ u: AdminUser) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(u.email).font(.rowTitle).foregroundStyle(Theme.text)
                Text("\(u.mb_url.replacingOccurrences(of: "https://", with: ""))  ·  \(u.request_count) calls  ·  active \(timeAgo(u.last_active))")
                    .font(.rowMeta).foregroundStyle(Theme.secondary)
            }
            Spacer()
            Text("View").font(.rowMeta).foregroundStyle(Theme.faint)
        }
        .padding(.vertical, 14).contentShape(Rectangle())
    }

    private func load() async {
        state.loading = true; state.error = ""
        do { state.items = try await API(session).users() }
        catch { state.error = error.localizedDescription }
        state.loading = false
    }
}

struct UserDetailView: View {
    @EnvironmentObject var session: Session
    @Environment(\.dismiss) private var dismiss
    let user: AdminUser
    var onRemoved: () -> Void
    @State private var activity: [ActivityItem] = []
    @State private var confirm = false
    @State private var error = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(user.email).font(.pageTitle).foregroundStyle(Theme.text)
                    Text("\(user.request_count) calls  ·  joined \(timeAgo(user.created_at))  ·  active \(timeAgo(user.last_active))")
                        .font(.rowMeta).foregroundStyle(Theme.secondary)
                }

                Button("Remove this person") { confirm = true }
                    .buttonStyle(FlatButton(destructive: true))

                if !error.isEmpty { Text(error).font(.rowMeta).foregroundStyle(Theme.danger) }

                Text("Recent activity").font(.section).foregroundStyle(Theme.secondary).padding(.top, 4)
                if activity.isEmpty {
                    Text("No activity recorded.").font(.rowMeta).foregroundStyle(Theme.faint)
                } else {
                    VStack(spacing: 0) {
                        ForEach(activity) { ActivityRow($0, showUser: false, emailFor: { _ in "" }) }
                    }
                }
            }
            .padding(24)
        }
        .background(Theme.bg)
        .navigationTitle("")
        .task { activity = (try? await API(session).userActivity(user.id)) ?? [] }
        .confirmationDialog("Remove \(user.email)? This deletes their access and cached data.",
                            isPresented: $confirm, titleVisibility: .visible) {
            Button("Remove", role: .destructive) { Task { await remove() } }
            Button("Cancel", role: .cancel) {}
        }
    }

    private func remove() async {
        do { try await API(session).deleteUser(user.id); onRemoved(); dismiss() }
        catch let err { error = err.localizedDescription }
    }
}
