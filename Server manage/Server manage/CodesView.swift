import SwiftUI

struct CodesView: View {
    @EnvironmentObject var session: Session
    @State private var codes: [InviteCode] = []
    @State private var note = ""
    @State private var error = ""
    @State private var busy = false
    @State private var justCreated: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                // Generate
                VStack(alignment: .leading, spacing: 10) {
                    Text("Generate a one-time code").font(.section).foregroundStyle(Theme.secondary)
                    HStack(spacing: 10) {
                        TextField("Label (optional, e.g. Alice)", text: $note)
                            .textFieldStyle(.plain).autocorrectionDisabled()
                            .padding(10).background(Card { Color.clear })
                        Button(busy ? "…" : "Generate") { Task { await create() } }
                            .buttonStyle(FlatButton(prominent: true)).disabled(busy)
                    }
                    if let c = justCreated {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack(spacing: 8) {
                                Text(c).font(.mono).foregroundStyle(Theme.text)
                                    .padding(.horizontal, 10).padding(.vertical, 6)
                                    .background(Card { Color.clear })
                                Text("works once").font(.rowMeta).foregroundStyle(Theme.faint)
                            }
                            ShareLink(item: inviteMessage(c)) {
                                Text("Share invite link")
                            }
                            .buttonStyle(FlatButton(prominent: true))
                            Text("Sends one link with the code and instructions built in — they just sign in.")
                                .font(.rowMeta).foregroundStyle(Theme.secondary)
                        }
                    }
                }
                .padding(16)
                .background(Card { Color.clear })

                if !error.isEmpty { Text(error).font(.rowMeta).foregroundStyle(Theme.danger) }

                Text("All codes").font(.section).foregroundStyle(Theme.secondary)
                LazyVStack(spacing: 0) {
                    if codes.isEmpty { EmptyHint(text: "No codes yet.") }
                    ForEach(codes) { row($0) }
                }
            }
            .padding(.horizontal, 24).padding(.top, 12)
        }
        .background(Theme.bg)
        .refreshable { await load() }
        .task { await load() }
    }

    private func row(_ c: InviteCode) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 3) {
                Text(c.code).font(.mono).foregroundStyle(c.used ? Theme.faint : Theme.text)
                let meta = c.used
                    ? "used by \(c.used_email ?? "someone")  ·  \(timeAgo(c.used_at))"
                    : (c.note.isEmpty ? "unused" : "unused  ·  \(c.note)")
                Text(meta).font(.rowMeta).foregroundStyle(Theme.secondary)
            }
            Spacer()
            Text(c.used ? "Used" : "Active")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(c.used ? Theme.faint : Theme.text)
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(RoundedRectangle(cornerRadius: 6).fill(Theme.goodBg))
            if !c.used {
                ShareLink(item: inviteMessage(c.code)) { Text("Share") }
                    .buttonStyle(FlatButton())
            }
            Button("Delete") { Task { await remove(c.code) } }
                .buttonStyle(FlatButton(destructive: true))
        }
        .padding(.vertical, 12)
        .overlay(alignment: .bottom) { Divider().overlay(Theme.hairline) }
    }

    // One shareable message: the magic enroll link (code built in) + instructions.
    private func inviteMessage(_ code: String) -> String {
        let base = session.baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
        return """
        You're invited to my ManageBac assistant.

        1. Open this link and sign in with your ManageBac email and password:
        \(base)/enroll?code=\(code)

        2. You'll get a personal link — add it to ChatGPT as a connector.

        The invite code is built into the link and works once.
        """
    }

    private func create() async {
        busy = true; error = ""
        do {
            let c = try await API(session).createCode(note: note)
            justCreated = c.code; note = ""
            await load()
        } catch let err { error = err.localizedDescription }
        busy = false
    }

    private func remove(_ code: String) async {
        do { try await API(session).deleteCode(code); await load() }
        catch let err { error = err.localizedDescription }
    }

    private func load() async {
        do { codes = try await API(session).codes() }
        catch let err { error = err.localizedDescription }
    }
}
