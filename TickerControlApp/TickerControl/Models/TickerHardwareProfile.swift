import Foundation

struct TickerProfile: Decodable, Sendable {
    let product_family: String
    let hardware: String
    let firmware: String
    let display: TickerDisplayGeometry
    let capabilities: TickerProfileCapabilities
}

struct TickerDisplayGeometry: Decodable, Sendable {
    let width: Int
    let height: Int
    let panel_count: Int
}

struct TickerProfileCapabilities: Decodable, Sendable {
    let modes: [String]
    let asset_cache: Bool
    let ota: Bool
    let color_depth: Int
}
