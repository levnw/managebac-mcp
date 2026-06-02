import SwiftUI

enum AdminTab: String, CaseIterable { case overview = "Overview", users = "People", codes = "Invite codes", activity = "Activity" }

struct RootView: View {
    @EnvironmentObject var session: Session
    @State private var tab: AdminTab = .overview

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                header
                Divider().overlay(Theme.hairline)
                tabBar
                Divider().overlay(Theme.hairline)
                content
            }
        }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("Server Manage").font(.pageTitle).foregroundStyle(Theme.text)
            Spacer()
            Button("Sign out") { session.logout() }.buttonStyle(FlatButton())
        }
        .padding(.horizontal, 24).padding(.top, 22).padding(.bottom, 16)
    }

    private var tabBar: some View {
        HStack(spacing: 4) {
            ForEach(AdminTab.allCases, id: \.self) { t in
                Button { tab = t } label: {
                    Text(t.rawValue)
                        .font(.system(size: 14, weight: tab == t ? .semibold : .regular))
                        .foregroundStyle(tab == t ? Theme.text : Theme.secondary)
                        .padding(.vertical, 12).padding(.horizontal, 10)
                        .overlay(alignment: .bottom) {
                            Rectangle().fill(tab == t ? Theme.accent : .clear).frame(height: 2)
                        }
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
        .padding(.horizontal, 18)
    }

    @ViewBuilder private var content: some View {
        switch tab {
        case .overview: OverviewView()
        case .users:    UsersView()
        case .codes:    CodesView()
        case .activity: ActivityView()
        }
    }
}

// Shared bits used by the list screens.
struct LoadState<T> {
    var items: [T] = []
    var loading = false
    var error = ""
}

struct EmptyHint: View {
    let text: String
    var body: some View {
        Text(text).font(.rowMeta).foregroundStyle(Theme.faint)
            .frame(maxWidth: .infinity, alignment: .center).padding(.top, 40)
    }
}
