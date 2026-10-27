import SwiftUI
import Foundation

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 3: (a, r, g, b) = (255, (int >> 8) * 17, (int >> 4 & 0xF) * 17, (int & 0xF) * 17)
        case 6: (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default: (a, r, g, b) = (1, 1, 1, 0)
        }
        self.init(.sRGB, red: Double(r) / 255, green: Double(g) / 255, blue:  Double(b) / 255, opacity: Double(a) / 255)
    }

    var isGrayscaleOrBlack: Bool {
        guard let components = self.cgColor?.components, components.count >= 3 else { return true }
        let r = components[0], g = components[1], b = components[2]
        let maxC = max(r, max(g, b))
        let delta = maxC - min(r, min(g, b))
        let saturation = maxC == 0 ? 0 : delta / maxC
        let brightness = (r * 0.299) + (g * 0.587) + (b * 0.114)
        return brightness < 0.1 || saturation < 0.15
    }
}
// Global helper visible to all views
func prioritizeVibrantColor(primary: String?, alternate: String?) -> Color {
    let pColor = Color(hex: primary ?? "#000000")
    let aColor = Color(hex: alternate ?? "#000000")
    if pColor.isGrayscaleOrBlack && !aColor.isGrayscaleOrBlack { return aColor }
    return pColor
}
// ==========================================
// MARK: - 1. DATA MODELS
// ==========================================
struct NativeLiquidGlass: ViewModifier {
    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
        return content
            .background(shape.fill(.regularMaterial).shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 5))
            .overlay(shape.strokeBorder(LinearGradient(gradient: Gradient(colors: [.white.opacity(0.3), .white.opacity(0.05)]), startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
            .clipShape(shape)
    }
}
extension View { func liquidGlass() -> some View { modifier(NativeLiquidGlass()) } }
func weatherIcon(for condition: String) -> String {
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
