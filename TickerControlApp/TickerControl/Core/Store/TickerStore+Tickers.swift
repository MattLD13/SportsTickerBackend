import Foundation

/// The ticker list, pairing, device settings, and the catalog.
extension TickerStore {
    /// Read the tickers of the controller group. The list is the member list. It does not change the selection.
    func refreshDevices() async {
        guard let scope = scope() else {
            devices = []
            updateStatus()
            return
        }
        guard let list = try? await api.send(API.tickers(), token: scope.token), isCurrent(scope) else { return }
        reachable = true
        devices = list.tickers
        if list.tickers.isEmpty { feed = [] }
        if isSportsOnly && settings.mode != "sports" {
            settings.mode = "sports"
            save()
        }
        updateStatus()
    }

    /// Exchange a pairing code for a controller token, then select the new ticker.
    /// With group sharing, the ticker joins the controller group of this app.
    @discardableResult
    func pair(code: String, name: String, shareGroup: Bool) async -> Bool {
        pairError = nil
        let group = shareGroup && session.canShareGroup ? (session.groupID, session.groupSecret) : (nil, nil)
        let result: PairResult
        do {
            result = try await api.send(API.pair(PairRequest(pairingCode: code, controllerGroupID: group.0, controllerGroupSecret: group.1)))
        } catch {
            pairError = error.localizedDescription
            return false
        }
        if let groupID = result.controllerGroupID {
            if let secret = result.controllerGroupSecret {
                guard session.saveGroup(id: groupID, secret: secret) else {
                    pairError = "Pairing failed: the shared app group could not be saved securely."
                    return false
                }
            } else {
                session.groupID = groupID
            }
        }
        guard session.saveToken(result.controllerToken, for: result.tickerID) else {
            pairError = "Pairing failed: the controller token could not be saved securely."
            return false
        }
        select(result.tickerID)
        pairSucceeded = true
        if let scope = scope(result.tickerID) {
            _ = try? await api.send(API.updateTicker(result.tickerID, TickerChange(name: name)), token: scope.token)
        }
        await refreshDevices()
        await refreshData()
        await refreshSpotify()
        return true
    }

    /// Unpair a ticker. The answer has a new pairing code for the ticker.
    func unpair(_ id: String) async {
        guard let scope = scope(id) else {
            connection = ConnectionStatus(text: "Unpair failed: ticker authorization is missing", tone: .failure)
            return
        }
        let code: PairingCode
        do { code = try await api.send(API.unpair(id), token: scope.token) } catch {
            connection = ConnectionStatus(text: "Unpair failed: \(error.localizedDescription)", tone: .failure)
            return
        }
        devices.removeAll { $0.id == id }
        session.removeToken(for: id)
        if activeTickerID == id {
            feed = []
            select(devices.first { session.token(for: $0.id) != nil }?.id)
        }
        pairCodeMessage = "Ticker unpaired. Its new pairing code is \(code.pairingCode)."
        await refreshDevices()
        await refreshData()
    }

    func showPairCode(for id: String) async {
        guard let scope = scope(id), let code = try? await api.send(API.pairingCode(id), token: scope.token) else {
            pairCodeMessage = "A pairing code could not be created."
            return
        }
        pairCodeMessage = "\(code.pairingCode)\nExpires in 10 minutes."
    }

    /// Change the hardware settings of one ticker, such as brightness or the stream delay.
    func updateDevice(_ id: String, _ patch: DisplaySettingsPatch) async {
        guard let scope = scope(id) else {
            operationError = "Pair this ticker before changing its settings."
            return
        }
        do {
            _ = try await api.send(API.updateTicker(id, TickerChange(displaySettings: patch)), token: scope.token)
            await refreshDevices()
        } catch {
            operationError = error.localizedDescription
        }
    }

    func reboot() async {
        guard let scope = scope() else {
            connection = ConnectionStatus(text: "Pair this ticker before requesting a reboot.", tone: .warning)
            return
        }
        do {
            _ = try await api.send(API.reboot(scope.tickerID), token: scope.token)
            connection = ConnectionStatus(text: "Reboot requested. The ticker will restart on its next poll.", tone: .good)
        } catch {
            connection = ConnectionStatus(text: "The reboot request failed.", tone: .failure)
        }
    }

    // Catalog

    /// Read the leagues, the mode symbols, and the teams of the first league with My Teams.
    func loadCatalog() async {
        if let catalog = try? await api.send(API.leagues()) {
            leagues = catalog.leagues
            if let first = catalog.leagues.first(where: { $0.isSport && $0.myTeamsEnabled != false }) { await loadTeams(first.id) }
        }
        if let catalog = try? await api.send(API.modes()) {
            modeSymbols = Dictionary(catalog.modes.map { ($0.id, $0.symbol) }) { first, _ in first }
        }
    }

    func loadTeams(_ league: String) async {
        guard teams[league] == nil, let catalog = try? await api.send(API.teams(league)) else { return }
        teams[league] = catalog.teams
    }
}
