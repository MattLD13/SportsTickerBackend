import AuthenticationServices
import CoreLocation
import Foundation
import NetworkExtension
import UIKit

/// The iOS services of the store: geocoding, the Wi-Fi name, Bluetooth Wi-Fi setup, and the Spotify web sign-in.
final class PhonePlatform: NSObject, TickerPlatform, CLLocationManagerDelegate, ASWebAuthenticationPresentationContextProviding {
    private let provisioner = BLEProvisioner()
    private var locationManager: CLLocationManager?
    private var authorization: CheckedContinuation<Void, Error>?
    private var webSession: ASWebAuthenticationSession?

    func geocode(_ query: String) async throws -> Place {
        let placemarks = try await CLGeocoder().geocodeAddressString(query)
        guard let place = placemarks.first, let location = place.location, let name = place.locality ?? place.name else {
            throw PlatformError("That weather location could not be found. Check its city or ZIP code.")
        }
        return Place(name: name, latitude: location.coordinate.latitude, longitude: location.coordinate.longitude)
    }

    // Wi-Fi name. iOS gives the name only to an app with location permission.

    func currentWiFiName() async throws -> String {
        guard CLLocationManager.locationServicesEnabled() else {
            throw PlatformError("Location Services must be enabled to detect the current Wi-Fi name.")
        }
        try await requestLocationPermission()
        guard let ssid = await NEHotspotNetwork.fetchCurrent()?.ssid, !ssid.isEmpty else {
            throw PlatformError("iOS could not identify the current Wi-Fi. Choose Different Wi-Fi.")
        }
        return ssid
    }

    private func requestLocationPermission() async throws {
        let manager = locationManager ?? CLLocationManager()
        manager.delegate = self
        locationManager = manager
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: return
        case .notDetermined:
            authorization?.resume(throwing: CancellationError())
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                authorization = continuation
                manager.requestWhenInUseAuthorization()
            }
        default: throw Self.locationDenied
        }
    }

    private static let locationDenied = PlatformError("Allow location access to detect the current Wi-Fi name, or choose Different Wi-Fi.")

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard let authorization, manager.authorizationStatus != .notDetermined else { return }
        self.authorization = nil
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse: authorization.resume()
        default: authorization.resume(throwing: Self.locationDenied)
        }
    }

    // Bluetooth Wi-Fi setup

    func provisionWiFi(code: String, ssid: String, password: String) async throws -> String? {
        try await provisioner.provision(code: code, ssid: ssid, password: password)
    }

    func cancelProvisioning() { provisioner.cancel() }

    // Spotify sign-in

    func authorizeSpotify(_ url: URL, callbackScheme: String) async throws -> URL {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<URL, Error>) in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: callbackScheme) { [weak self] callback, error in
                self?.webSession = nil
                if let callback {
                    continuation.resume(returning: callback)
                } else {
                    continuation.resume(throwing: PlatformError(error?.localizedDescription ?? "Spotify authorization was cancelled."))
                }
            }
            session.presentationContextProvider = self
            webSession = session
            if !session.start() {
                webSession = nil
                continuation.resume(throwing: PlatformError("Spotify authorization could not open."))
            }
        }
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        let windows = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows)
        return windows.first(where: \.isKeyWindow) ?? ASPresentationAnchor()
    }
}
