import Foundation

/// One ticker of the controller group, as `GET /tickers` returns it.
nonisolated struct TickerRecord: Decodable, Identifiable {
    let id: String
    let name: String
    let settings: DisplaySettings
    let lastSeen: Double?
    let profile: TickerProfile?
    let reportedModes: Set<String>

    private enum Keys: String, CodingKey { case ticker_id, name, display_settings, device, profile }
    private enum DeviceKeys: String, CodingKey { case last_seen_at, metadata }
    private enum MetadataKeys: String, CodingKey { case capabilities }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        id = try c.decode(String.self, forKey: .ticker_id)
        name = try c.decode(String.self, forKey: .name)
        settings = try c.decode(DisplaySettings.self, forKey: .display_settings)
        profile = try c.decodeIfPresent(TickerProfile.self, forKey: .profile)
        let device = try c.nestedContainer(keyedBy: DeviceKeys.self, forKey: .device)
        lastSeen = try device.decodeIfPresent(Double.self, forKey: .last_seen_at)
        let metadata = try? device.nestedContainer(keyedBy: MetadataKeys.self, forKey: .metadata)
        reportedModes = Set(((try? metadata?.decodeIfPresent([String].self, forKey: .capabilities)) ?? nil)?.map { $0.lowercased() } ?? [])
    }

    init(id: String, name: String, settings: DisplaySettings = DisplaySettings(), lastSeen: Double? = nil,
         profile: TickerProfile? = nil, reportedModes: Set<String> = []) {
        self.id = id; self.name = name; self.settings = settings; self.lastSeen = lastSeen
        self.profile = profile; self.reportedModes = reportedModes
    }

    /// The modes of the ticker: the modes that the device reports, or else the modes of its profile.
    var modes: Set<String> {
        reportedModes.isEmpty ? Set(profile?.capabilities.modes.map { $0.lowercased() } ?? []) : reportedModes
    }

    /// A ticker that shows sports only, such as a Mini with the sports firmware.
    var isSportsOnly: Bool { modes == ["sports"] }

    /// The modes that a schedule block can select on this ticker.
    var schedulableModes: [String] {
        if let modes = profile?.capabilities.modes, !modes.isEmpty { return modes }
        return DisplayMode.all.filter { modes.isEmpty || modes.contains($0) }
    }
}

nonisolated struct TickerList: Decodable { let tickers: [TickerRecord] }

nonisolated struct TickerProfile: Decodable {
    let productFamily: String
    let hardware: String
    let firmware: String
    let display: Display
    let capabilities: Capabilities

    struct Display: Decodable { let width: Int; let height: Int; let panelCount: Int
        enum CodingKeys: String, CodingKey { case width, height, panelCount = "panel_count" }
    }
    struct Capabilities: Decodable { let modes: [String]; let assetCache: Bool; let ota: Bool; let colorDepth: Int
        enum CodingKeys: String, CodingKey { case modes, assetCache = "asset_cache", ota, colorDepth = "color_depth" }
    }
    enum CodingKeys: String, CodingKey { case productFamily = "product_family", hardware, firmware, display, capabilities }

    var displayName: String {
        switch productFamily {
        case "full": return "Ticker Six"
        case "mini": return "Ticker Mini"
        default: return "Ticker"
        }
    }
}

nonisolated enum DisplayMode {
    static let all = ["sports", "stock", "weather", "music", "flights", "airports", "clock"]
}

nonisolated struct PairRequest: Encodable {
    let pairingCode: String
    let controllerGroupID: String?
    let controllerGroupSecret: String?
    enum CodingKeys: String, CodingKey {
        case pairingCode = "pairing_code", controllerGroupID = "controller_group_id", controllerGroupSecret = "controller_group_secret"
    }
}

nonisolated struct PairResult: Decodable {
    let tickerID: String
    let controllerToken: String
    let controllerGroupID: String?
    let controllerGroupSecret: String?
    enum CodingKeys: String, CodingKey {
        case tickerID = "ticker_id", controllerToken = "controller_token"
        case controllerGroupID = "controller_group_id", controllerGroupSecret = "controller_group_secret"
    }
}

nonisolated struct PairingCode: Decodable {
    let pairingCode: String
    enum CodingKeys: String, CodingKey { case pairingCode = "pairing_code" }
}
