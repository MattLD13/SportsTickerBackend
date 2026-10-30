import Foundation

nonisolated struct SpotifyAccount: Decodable, Identifiable, Equatable {
    let id: String
    let displayName: String
    let status: String
    let connected: Bool
    let priority: Bool
    enum CodingKeys: String, CodingKey { case id = "spotify_account_id", displayName = "display_name", status, connected, priority }
}

nonisolated struct SpotifyStatus: Decodable {
    let connected: Bool
    let status: String
    let displayName: String?
    let accounts: [SpotifyAccount]
    enum CodingKeys: String, CodingKey { case connected, status, displayName = "display_name", accounts }
}

nonisolated struct SpotifyLogin: Decodable {
    let attemptID: String
    let authorizationURL: URL
    enum CodingKeys: String, CodingKey { case attemptID = "attempt_id", authorizationURL = "authorization_url" }
}

/// The body of `PATCH /tickers/<id>/spotify/priority`. A null account lets the ticker follow the playing account.
nonisolated struct SpotifyPriority: Encodable {
    let spotifyAccountID: String?
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(spotifyAccountID, forKey: .spotifyAccountID)
    }
    enum CodingKeys: String, CodingKey { case spotifyAccountID = "spotify_account_id" }
}
