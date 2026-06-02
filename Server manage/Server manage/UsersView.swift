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
            .navigationDestination(for: AdminUser.self) { UserDetailView(user: $0, refresh: { Task { await load() } }) }
            .refreshable { await load() }
        }
        .task { await load() }
    }

    private func row(_ u: AdminUser) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(u.email).font(.rowTitle).foregroundStyle(u.approved && u.enabled ? Theme.text : Theme.faint)
                    if !u.approved { StatusTag(text: "Pending") }
                    else if !u.enabled { StatusTag(text: "Paused") }
                }
                let metaParts = [u.mb_url.replacingOccurrences(of: "https://", with: ""),
                                 "\(u.request_count) calls", "active \(timeAgo(u.last_active))"]
                Text(metaParts.joined(separator: "  ·  "))
                    .font(.rowMeta).foregroundStyle(Theme.secondary)
                if !u.note.isEmpty {
                    Text(u.note).font(.rowMeta).foregroundStyle(Theme.faint).italic()
                }
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

// A small text pill used for status (no icons).
struct StatusTag: View {
    let text: String
    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(Theme.secondary)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 5).fill(Theme.goodBg))
    }
}

struct UserDetailView: View {
    @EnvironmentObject var session: Session
    @Environment(\.dismiss) private var dismiss
    let user: AdminUser
    var refresh: () -> Void

    @State private var enabled: Bool
    @State private var approved: Bool
    @State private var token: String
    @State private var note: String
    @State private var noteSaved = false
    @State private var activity: [ActivityItem] = []
    @State private var confirm = false
    @State private var error = ""
    @State private var busy = false
    @State private var copied = false
    @State private var regenerated = false

    init(user: AdminUser, refresh: @escaping () -> Void) {
        self.user = user
        self.refresh = refresh
        _enabled = State(initialValue: user.enabled)
        _approved = State(initialValue: user.approved)
        _token = State(initialValue: user.token)
        _note = State(initialValue: user.note)
    }

    private var connector: String { connectorURL(base: session.baseURL, token: token) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                // Header
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Text(user.email).font(.pageTitle).foregroundStyle(Theme.text)
                        if !approved { StatusTag(text: "Pending") }
                        else if !enabled { StatusTag(text: "Paused") }
                    }
                    Text("\(user.request_count) calls  ·  joined \(timeAgo(user.created_at))  ·  active \(timeAgo(user.last_active))")
                        .font(.rowMeta).foregroundStyle(Theme.secondary)
                }

                // Approval — pending users can't use their link until approved.
                if !approved {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("This person is waiting for approval. Their link won't work until you approve.")
                            .font(.rowMeta).foregroundStyle(Theme.secondary)
                        Button("Approve") { Task { await approve() } }
                            .buttonStyle(FlatButton(prominent: true)).disabled(busy)
                    }
                }

                // Note
                VStack(alignment: .leading, spacing: 8) {
                    Text("Note").font(.section).foregroundStyle(Theme.secondary)
                    TextField("Add a private note about this person…", text: $note, axis: .vertical)
                        .textFieldStyle(.plain).lineLimit(2...5)
                        .padding(10).background(Card { Color.clear })
                    Button(noteSaved ? "Saved" : "Save note") { Task { await saveNote() } }
                        .buttonStyle(FlatButton()).disabled(busy)
                }

                // Connector link
                VStack(alignment: .leading, spacing: 8) {
                    Text("Connector link").font(.section).foregroundStyle(Theme.secondary)
                    Text(connector).font(.mono).foregroundStyle(Theme.text)
                        .textSelection(.enabled)
                        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Card { Color.clear })
                    HStack(spacing: 8) {
                        Button(copied ? "Copied" : "Copy link") {
                            copyToClipboard(connector); copied = true
                        }.buttonStyle(FlatButton())
                        if regenerated {
                            Text("New link — old one no longer works. Re-send this.")
                                .font(.rowMeta).foregroundStyle(Theme.secondary)
                        }
                    }
                }

                if !error.isEmpty { Text(error).font(.rowMeta).foregroundStyle(Theme.danger) }

                // Actions
                VStack(alignment: .leading, spacing: 8) {
                    Text("Manage").font(.section).foregroundStyle(Theme.secondary)
                    HStack(spacing: 10) {
                        Button(enabled ? "Pause access" : "Resume access") { Task { await togglePause() } }
                            .buttonStyle(FlatButton()).disabled(busy)
                        Button("Regenerate link") { Task { await regenerate() } }
                            .buttonStyle(FlatButton()).disabled(busy)
                    }
                    Button("Remove this person") { confirm = true }
                        .buttonStyle(FlatButton(destructive: true)).disabled(busy)
                }

                // Activity
                Text("Recent activity").font(.section).foregroundStyle(Theme.secondary).padding(.top, 2)
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

    private func approve() async {
        busy = true; error = ""
        do { try await API(session).approveUser(user.id, approved: true); approved = true; refresh() }
        catch let err { error = err.localizedDescription }
        busy = false
    }

    private func saveNote() async {
        busy = true; error = ""
        do { try await API(session).setNote(user.id, note: note); noteSaved = true; refresh() }
        catch let err { error = err.localizedDescription }
        busy = false
    }

    private func togglePause() async {
        busy = true; error = ""
        do { try await API(session).pauseUser(user.id, enabled: !enabled); enabled.toggle(); refresh() }
        catch let err { error = err.localizedDescription }
        busy = false
    }

    private func regenerate() async {
        busy = true; error = ""; copied = false
        do { token = try await API(session).regenerateToken(user.id); regenerated = true; refresh() }
        catch let err { error = err.localizedDescription }
        busy = false
    }

    private func remove() async {
        do { try await API(session).deleteUser(user.id); refresh(); dismiss() }
        catch let err { error = err.localizedDescription }
    }
}
