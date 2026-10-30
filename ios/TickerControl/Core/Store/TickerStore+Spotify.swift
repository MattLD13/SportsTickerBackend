import Foundation

/// The Spotify accounts that feed Music mode.
extension TickerStore {
    static let callbackScheme = "tickercontrol"

    func refreshSpotify() async {
        guard let scope = scope() else {
            spotify.status = "Connect a Ticker first"
            spotify.accountName = nil
            spotify.accounts = []
            return
        }
        do {
            let status = try await api.send(API.spotify(scope.tickerID), token: scope.token)
            guard isCurrent(scope) else { return }
            spotify.status = status.connected ? "Connected" : "Not connected"
            spotify.accountName = status.displayName
            spotify.accounts = status.accounts
            spotify.error = nil
        } catch {
            guard isCurrent(scope) else { return }
            spotify.status = "Spotify unavailable"
            spotify.error = error.localizedDescription
        }
    }

    /// Link one more Spotify account. Spotify returns to the app through the `tickercontrol` URL scheme.
    func connectSpotify() async {
        guard let scope = scope() else {
            spotify.error = "Pair with a Ticker before connecting Spotify."
            return
        }
        spotify.connecting = true
        spotify.error = nil
        defer { spotify.connecting = false }
        let login: SpotifyLogin
        do { login = try await api.send(API.spotifyLogin(scope.tickerID), token: scope.token) } catch {
            spotify.error = "Spotify authorization could not start."
            return
        }
        do {
            let callback = try await platform.authorizeSpotify(login.authorizationURL, callbackScheme: Self.callbackScheme)
            guard isCurrent(scope) else { return }
            await handleSpotifyCallback(callback)
        } catch {
            spotify.error = error.localizedDescription
        }
    }

    /// Read the result of a Spotify login from its return URL.
    func handleSpotifyCallback(_ url: URL) async {
        let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        guard items.contains(where: { $0.name == "attempt_id" }) else { return }
        if items.first(where: { $0.name == "status" })?.value == "connected" {
            await refreshSpotify()
        } else {
            spotify.error = "Spotify authorization did not complete."
        }
    }

    /// Unlink one account, or every account when `account` is nil.
    func disconnectSpotify(_ account: String? = nil) async {
        guard let scope = scope() else { return }
        do {
            _ = try await api.send(API.unlinkSpotify(scope.tickerID, account: account), token: scope.token)
            spotify.error = nil
            await refreshSpotify()
        } catch {
            spotify.error = "Spotify could not disconnect."
        }
    }

    /// Show one account first, or follow the playing account when `account` is nil.
    func setSpotifyPriority(_ account: String?) async {
        guard let scope = scope() else { return }
        do {
            _ = try await api.send(API.spotifyPriority(scope.tickerID, account: account), token: scope.token)
            spotify.error = nil
            await refreshSpotify()
        } catch {
            spotify.error = "Spotify priority could not update."
        }
    }
}
