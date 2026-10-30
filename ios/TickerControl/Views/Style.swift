import Foundation
import SwiftUI
import UIKit

/// The gradient behind every screen.
struct AppBackground: View {
    var body: some View {
        LinearGradient(colors: [Color(red: 0.22, green: 0.28, blue: 0.35), Color(red: 0.05, green: 0.07, blue: 0.10)],
                       startPoint: .top, endPoint: .bottom)
            .ignoresSafeArea()
    }
}

/// A frosted card with a light edge.
struct LiquidGlass: ViewModifier {
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        content
            .background(shape.fill(.regularMaterial).shadow(color: .black.opacity(0.15), radius: 10, x: 0, y: 5))
            .overlay(shape.strokeBorder(GlassEdge.gradient, lineWidth: 1))
            .clipShape(shape)
    }
}

enum GlassEdge {
    static let gradient = LinearGradient(colors: [.white.opacity(0.3), .white.opacity(0.05)], startPoint: .topLeading, endPoint: .bottomTrailing)
}

extension View {
    func liquidGlass() -> some View { modifier(LiquidGlass()) }

    /// The outline of a feed card in its accent color.
    func feedCard(_ accent: Color, padding: CGFloat = 12) -> some View {
        self.padding(padding)
            .background(Color.white.opacity(0.08))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(accent.opacity(0.35), lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
    }

    /// A small caption in capitals above a group of controls.
    func sectionHeader() -> some View { self.font(.caption).bold().foregroundStyle(.secondary) }
}

/// The title of a tab screen.
struct ScreenTitle: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 34, weight: .bold)).foregroundColor(.white)
    }
}

extension Color {
    /// A color from "#RGB", "#RRGGBB", or "#AARRGGBB". Another value gives clear black.
    init(hex: String) {
        let digits = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var value: UInt64 = 0
        Scanner(string: digits).scanHexInt64(&value)
        let a, r, g, b: UInt64
        switch digits.count {
        case 3: (a, r, g, b) = (255, (value >> 8) * 17, (value >> 4 & 0xF) * 17, (value & 0xF) * 17)
        case 6: (a, r, g, b) = (255, value >> 16, value >> 8 & 0xFF, value & 0xFF)
        case 8: (a, r, g, b) = (value >> 24, value >> 16 & 0xFF, value >> 8 & 0xFF, value & 0xFF)
        default: (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(.sRGB, red: Double(r) / 255, green: Double(g) / 255, blue: Double(b) / 255, opacity: Double(a) / 255)
    }

    var isMuted: Bool {
        guard let components = UIColor(self).cgColor.components, components.count >= 3 else { return true }
        let r = components[0], g = components[1], b = components[2]
        let high = max(r, g, b)
        let saturation = high == 0 ? 0 : (high - min(r, g, b)) / high
        let brightness = r * 0.299 + g * 0.587 + b * 0.114
        return brightness < 0.1 || saturation < 0.15
    }

    /// The team color for a card background: the primary color, or the alternate color when the primary is gray or black.
    static func team(_ side: TeamSide) -> Color {
        let primary = Color(hex: side.color ?? "#000000")
        let alternate = Color(hex: side.altColor ?? "#000000")
        return primary.isMuted && !alternate.isMuted ? alternate : primary
    }
}

/// The SF Symbol for a weather condition, such as "Partly Cloudy".
func weatherSymbol(_ condition: String) -> String {
    let c = condition.uppercased()
    if c.contains("CLEAR") || c.contains("SUNNY") { return "sun.max.fill" }
    if c.contains("PARTLY") { return "cloud.sun.fill" }
    if c.contains("CLOUD") || c.contains("OVERCAST") { return "cloud.fill" }
    if c.contains("RAIN") || c.contains("DRIZZLE") || c.contains("SHOWER") { return "cloud.rain.fill" }
    if c.contains("SNOW") { return "cloud.snow.fill" }
    if c.contains("THUNDER") { return "cloud.bolt.rain.fill" }
    if c.contains("FOG") || c.contains("MIST") || c.contains("HAZE") { return "cloud.fog.fill" }
    if c.contains("FREEZING") { return "thermometer.snowflake" }
    return "cloud.fill"
}

/// A team logo, or its abbreviation while the logo loads.
struct TeamLogo: View {
    let url: String?
    let abbr: String
    let size: CGFloat

    var body: some View {
        AsyncImage(url: URL(string: url ?? "")) { phase in
            if let image = phase.image {
                image.resizable().scaledToFit()
            } else {
                Text(abbr).font(.system(size: size * 0.4, weight: .bold)).foregroundColor(.white.opacity(0.8))
            }
        }
        .frame(width: size, height: size)
    }
}

/// A square icon tile on the left of a feed card.
struct CardIcon: View {
    let symbol: String
    let color: Color
    var tint: Color? = nil
    var font: Font = .system(size: 28)

    var body: some View {
        Image(systemName: symbol)
            .font(font).foregroundStyle(tint ?? color)
            .frame(width: 54, height: 54)
            .background(color.opacity(0.14))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// A wide option button: blue while selected.
struct ChoiceButton: View {
    let title: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title).font(.headline)
                .frame(maxWidth: .infinity).padding(.vertical, 12)
                .background(selected ? Color(red: 0.0, green: 0.47, blue: 1.0) : Color.white.opacity(0.05))
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(selected ? Color.blue : Color.white.opacity(0.1), lineWidth: 1))
                .foregroundColor(.white)
        }
    }
}

/// A smaller option button of the Modes screen, with an optional symbol.
struct OptionButton: View {
    let title: String
    var symbol: String? = nil
    var selectedColor: Color = .blue
    var cornerRadius: CGFloat = 12
    var verticalPadding: CGFloat = 12
    let selected: Bool
    let action: () -> Void

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        Button(action: action) {
            Group {
                if let symbol { Label(title, systemImage: symbol) } else { Text(title) }
            }
            .font(.subheadline).bold()
            .frame(maxWidth: .infinity).padding(.vertical, verticalPadding)
            .background(selected ? selectedColor.opacity(0.8) : Color.white.opacity(0.05))
            .clipShape(shape)
            .overlay(shape.stroke(selected ? selectedColor : Color.white.opacity(0.1), lineWidth: 1))
            .foregroundColor(.white)
        }
    }
}
