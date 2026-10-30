import Foundation

/// A geocoded weather location.
struct Place: Equatable {
    let name: String
    let latitude: Double
    let longitude: Double
}

/// The services of the phone that the store uses. The app implements them with iOS frameworks.
protocol TickerPlatform {
    /// Find a city or a postal code.
    func geocode(_ query: String) async throws -> Place
    /// Return the name of the Wi-Fi network of the phone.
    func currentWiFiName() async throws -> String
    /// Send Wi-Fi settings to a ticker in setup mode over Bluetooth. Return its app pairing code when it has one.
    func provisionWiFi(code: String, ssid: String, password: String) async throws -> String?
    func cancelProvisioning()
    /// Open a web sign-in and return the URL that the browser opens at the end.
    func authorizeSpotify(_ url: URL, callbackScheme: String) async throws -> URL
}

/// A failure that the platform reports with a message for the user.
struct PlatformError: LocalizedError, Equatable {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
