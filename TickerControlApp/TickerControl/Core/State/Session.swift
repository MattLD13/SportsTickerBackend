import Foundation

/// Stores secrets, such as the Keychain on iOS.
protocol CredentialStore {
    func read(service: String, account: String) -> String?
    func write(_ value: String, service: String, account: String) -> Bool
    func remove(service: String, account: String)
}

/// Stores small values, such as `UserDefaults`.
protocol ValueStore {
    func string(forKey key: String) -> String?
    func stringArray(forKey key: String) -> [String]?
    func set(_ value: Any?, forKey key: String)
}

extension UserDefaults: ValueStore {}

/// The pairing state of this app: the server, the active ticker, the controller tokens, and the controller group.
/// A controller group shares My Teams and Spotify across the tickers that this app paired with group sharing.
/// The keys are the keys of earlier app releases, so an update keeps every pairing.
final class Session {
    static let defaultServer = "https://ticker.mattdicks.org"
    private static let tokenService = "matt.TickerControl.controller-token"
    private static let groupSecretService = "matt.TickerControl.controller-group-secret"

    private let values: any ValueStore
    private let credentials: any CredentialStore

    init(values: any ValueStore, credentials: any CredentialStore) {
        self.values = values
        self.credentials = credentials
    }

    var serverURL: String {
        get { values.string(forKey: "serverURL") ?? Self.defaultServer }
        set { values.set(newValue, forKey: "serverURL") }
    }

    var activeTickerID: String? {
        get { values.string(forKey: "latchedTickerID") }
        set { values.set(newValue, forKey: "latchedTickerID") }
    }

    var groupID: String? {
        get { values.string(forKey: "controllerGroupID") }
        set { values.set(newValue, forKey: "controllerGroupID") }
    }

    /// My Teams belong to the app, so every paired ticker shows the same teams.
    var sharedTeams: [String]? {
        get { values.stringArray(forKey: "sharedMyTeams") }
        set { values.set(newValue, forKey: "sharedMyTeams") }
    }

    func token(for tickerID: String) -> String? { credentials.read(service: Self.tokenService, account: tickerID) }

    func saveToken(_ token: String, for tickerID: String) -> Bool {
        credentials.write(token, service: Self.tokenService, account: tickerID)
    }

    func removeToken(for tickerID: String) { credentials.remove(service: Self.tokenService, account: tickerID) }

    /// The group secret belongs to one server.
    var groupSecret: String? { credentials.read(service: Self.groupSecretService, account: APIClient.normalized(serverURL)) }

    func saveGroup(id: String, secret: String) -> Bool {
        guard credentials.write(secret, service: Self.groupSecretService, account: APIClient.normalized(serverURL)) else { return false }
        groupID = id
        return true
    }

    var canShareGroup: Bool { groupID != nil && groupSecret != nil }

    /// The token for a request about one ticker. In a group, the token of any paired ticker controls the group.
    func authorization(for tickerID: String, among tickerIDs: [String]) -> String? {
        if let token = token(for: tickerID) { return token }
        guard groupID != nil else { return nil }
        return tickerIDs.lazy.compactMap(token(for:)).first
    }
}
