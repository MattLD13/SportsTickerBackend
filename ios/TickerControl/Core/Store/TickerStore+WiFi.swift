import Foundation

/// Wi-Fi setup of a new ticker over Bluetooth, then app pairing with the code that the ticker returns.
extension TickerStore {
    func detectWiFi() async {
        do {
            let name = try await platform.currentWiFiName()
            wifi.detectedSSID = name
            wifi.ssid = name
            wifi.error = nil
        } catch {
            wifi.error = error.localizedDescription
        }
    }

    func startWiFiSetup() async {
        let code = wifi.code.trimmingCharacters(in: .whitespacesAndNewlines)
        let ssid = wifi.ssid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard code.count == 6, code.allSatisfy(\.isASCII), code.allSatisfy(\.isNumber) else {
            wifi.error = "Enter the six-digit WIFI PIN shown on the ticker."
            return
        }
        guard !ssid.isEmpty, ssid.utf8.count <= 32, wifi.password.utf8.count <= 64 else {
            wifi.error = "Enter a Wi-Fi name of up to 32 bytes and a password of up to 64 bytes. Open networks need no password."
            return
        }
        wifi.error = nil
        wifi.status = "Searching for the ticker over Bluetooth..."
        wifi.inProgress = true
        defer { wifi.inProgress = false }
        let pairing: String?
        do { pairing = try await platform.provisionWiFi(code: code, ssid: ssid, password: wifi.password) } catch {
            wifi.status = ""
            wifi.error = error.localizedDescription
            return
        }
        guard let pairing else {
            wifi.status = "Wi-Fi saved. Wait for APP PAIR, then enter that code in Add ticker."
            return
        }
        wifi.status = "Wi-Fi saved. Pairing this app with the ticker..."
        if await pair(code: pairing, name: pairName.isEmpty ? "My Ticker" : pairName, shareGroup: canShareGroup) {
            wifi.status = "Wi-Fi saved. Ticker paired successfully."
        } else {
            wifi.status = ""
            wifi.error = "Wi-Fi saved, but app pairing failed: \(pairError ?? "unknown error")"
        }
    }

    func cancelWiFiSetup() {
        platform.cancelProvisioning()
        wifi.inProgress = false
        wifi.password = ""
    }
}
