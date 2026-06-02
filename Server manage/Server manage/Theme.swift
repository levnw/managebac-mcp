import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

// Copy text to the system clipboard (works on iPhone and Mac).
func copyToClipboard(_ s: String) {
    #if os(iOS)
    UIPasteboard.general.string = s
    #elseif os(macOS)
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(s, forType: .string)
    #endif
}

// Build a user's connector URL from the server base + their token.
func connectorURL(base: String, token: String) -> String {
    base.trimmingCharacters(in: CharacterSet(charactersIn: "/ ")) + "/mcp?key=" + token
}

// Minimal, Notion-like design system. Text and rules only — no icons, no emoji.
enum Theme {
    static let bg          = Color(white: 0.98)
    static let surface     = Color.white
    static let text        = Color(white: 0.10)
    static let secondary   = Color(white: 0.45)
    static let faint       = Color(white: 0.62)
    static let hairline    = Color(white: 0.89)
    static let accent      = Color(white: 0.10)   // near-black, used sparingly
    static let danger      = Color(red: 0.72, green: 0.18, blue: 0.16)
    static let goodBg      = Color(white: 0.94)

    static let radius: CGFloat = 8
    static let pad:    CGFloat = 16
}

extension Font {
    static let pageTitle  = Font.system(size: 26, weight: .semibold)
    static let section    = Font.system(size: 13, weight: .semibold)
    static let rowTitle   = Font.system(size: 15, weight: .medium)
    static let rowMeta    = Font.system(size: 13, weight: .regular)
    static let mono       = Font.system(size: 15, weight: .medium, design: .monospaced)
}

// A plain, bordered text button — the only button style in the app.
struct FlatButton: ButtonStyle {
    var prominent = false
    var destructive = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(prominent ? Color.white : (destructive ? Theme.danger : Theme.text))
            .padding(.horizontal, 14).padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: Theme.radius)
                    .fill(prominent ? Theme.accent : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius)
                    .stroke(prominent ? Color.clear : Theme.hairline, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.6 : 1)
            .contentShape(Rectangle())
    }
}

// A bordered card container.
struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .background(Theme.surface)
            .overlay(RoundedRectangle(cornerRadius: Theme.radius).stroke(Theme.hairline, lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: Theme.radius))
    }
}

// Relative "time ago" from a unix timestamp.
func timeAgo(_ ts: Int?) -> String {
    guard let ts, ts > 0 else { return "never" }
    let secs = Int(Date().timeIntervalSince1970) - ts
    if secs < 60 { return "just now" }
    if secs < 3600 { return "\(secs/60)m ago" }
    if secs < 86400 { return "\(secs/3600)h ago" }
    return "\(secs/86400)d ago"
}
