import SwiftUI

struct LoginView: View {
    @EnvironmentObject var session: Session
    @State private var password = ""
    @State private var error = ""
    @State private var busy = false

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Server Manage").font(.pageTitle).foregroundStyle(Theme.text)
                    Text("Admin sign in").font(.rowMeta).foregroundStyle(Theme.secondary)
                }

                VStack(alignment: .leading, spacing: 14) {
                    field("Server URL", text: $session.baseURL)
                    field("Username", text: $session.username)
                    secureField("Password", text: $password)
                }

                if !error.isEmpty {
                    Text(error).font(.rowMeta).foregroundStyle(Theme.danger)
                }

                Button(busy ? "Signing in…" : "Sign in") { Task { await signIn() } }
                    .buttonStyle(FlatButton(prominent: true))
                    .disabled(busy || session.username.isEmpty || password.isEmpty)

                Spacer()
            }
            .padding(28)
            .frame(maxWidth: 420, alignment: .leading)
        }
    }

    private func signIn() async {
        busy = true; error = ""
        do {
            try await API(session).login(username: session.username, password: password)
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }

    private func field(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.section).foregroundStyle(Theme.secondary)
            TextField("", text: text)
                .textFieldStyle(.plain)
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .padding(10)
                .background(Card { Color.clear })
        }
    }

    private func secureField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.section).foregroundStyle(Theme.secondary)
            SecureField("", text: text)
                .textFieldStyle(.plain)
                .padding(10)
                .background(Card { Color.clear })
                .onSubmit { Task { await signIn() } }
        }
    }
}
