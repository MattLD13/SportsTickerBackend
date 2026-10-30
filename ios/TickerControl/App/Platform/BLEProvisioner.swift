import CoreBluetooth
import CryptoKit
import Foundation

/// Sends the home Wi-Fi settings to a ticker in setup mode over Bluetooth.
/// The setup PIN and the challenge of the ticker derive an AES-GCM key, so only the ticker that shows the PIN can read them.
final class BLEProvisioner: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private static let service = CBUUID(string: "8F8B0001-6E2A-4D8A-9F31-8D4B77F0B001")
    private static let challenge = CBUUID(string: "8F8B0002-6E2A-4D8A-9F31-8D4B77F0B001")
    private static let credentials = CBUUID(string: "8F8B0003-6E2A-4D8A-9F31-8D4B77F0B001")
    private static let result = CBUUID(string: "8F8B0004-6E2A-4D8A-9F31-8D4B77F0B001")
    private static let pairing = CBUUID(string: "8F8B0005-6E2A-4D8A-9F31-8D4B77F0B001")
    private static let protocolInfo = Data("SportsTicker BLE Wi-Fi v1".utf8)

    private struct Request { let code: String; let ssid: String; let password: String }

    private var request: Request?
    private var completion: CheckedContinuation<String?, Error>?
    private var central: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var characteristics: [CBUUID: CBCharacteristic] = [:]
    private var chunks: [Data] = []
    private var nextChunk = 0
    private var pairingCode: String?
    private var timeout: Task<Void, Never>?

    /// Return the app pairing code of the ticker, or nil when the ticker has no code yet.
    func provision(code: String, ssid: String, password: String) async throws -> String? {
        finish(.failure(CancellationError()))
        return try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<String?, Error>) in
            completion = continuation
            request = Request(code: code, ssid: ssid, password: password)
            central = CBCentralManager(delegate: self, queue: .main)
            timeout = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 60_000_000_000)
                guard !Task.isCancelled else { return }
                self?.fail("Ticker setup timed out. Move closer, check its WIFI PIN, and try again.")
            }
        }
    }

    func cancel() { finish(.failure(CancellationError())) }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            central.scanForPeripherals(withServices: [Self.service], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        case .poweredOff: fail("Turn on Bluetooth to set up the ticker.")
        case .unauthorized: fail("Allow Bluetooth access in iPhone Settings to set up the ticker.")
        case .unsupported: fail("This device does not support Bluetooth ticker setup.")
        default: break
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        self.peripheral = peripheral
        peripheral.delegate = self
        central.stopScan()
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        peripheral.discoverServices([Self.service])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        fail(error?.localizedDescription ?? "The ticker could not be reached over Bluetooth.")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == Self.service }) else {
            fail(error?.localizedDescription ?? "The ticker Bluetooth service is unavailable.")
            return
        }
        peripheral.discoverCharacteristics([Self.challenge, Self.credentials, Self.result, Self.pairing], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error { fail(error.localizedDescription); return }
        characteristics = Dictionary((service.characteristics ?? []).map { ($0.uuid, $0) }) { first, _ in first }
        guard let challenge = characteristics[Self.challenge], let pairing = characteristics[Self.pairing],
              characteristics[Self.credentials] != nil, characteristics[Self.result] != nil else {
            fail("The ticker Bluetooth setup service is incomplete.")
            return
        }
        peripheral.readValue(for: challenge)
        peripheral.readValue(for: pairing)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let data = characteristic.value else {
            fail(error?.localizedDescription ?? "The ticker returned no Bluetooth setup response.")
            return
        }
        let text = String(data: data, encoding: .utf8)
        switch characteristic.uuid {
        case Self.pairing:
            pairingCode = text == "NONE" ? nil : text
        case Self.challenge:
            do {
                chunks = try sealedChunks(challenge: data)
                nextChunk = 0
                writeNextChunk()
            } catch {
                fail("The ticker setup message could not be secured.")
            }
        case Self.result:
            if text == "OK" { finish(.success(pairingCode)) } else { fail(text ?? "The ticker rejected the Wi-Fi settings.") }
        default: break
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error { fail(error.localizedDescription); return }
        nextChunk += 1
        writeNextChunk()
    }

    private func writeNextChunk() {
        guard let peripheral, let credentials = characteristics[Self.credentials] else { return }
        if nextChunk < chunks.count {
            peripheral.writeValue(chunks[nextChunk], for: credentials, type: .withResponse)
        } else if let result = characteristics[Self.result] {
            peripheral.readValue(for: result)
        }
    }

    /// Seal the Wi-Fi settings, then split the envelope into numbered 120-character chunks such as "0/3:...".
    private func sealedChunks(challenge: Data) throws -> [Data] {
        guard let request else { throw CancellationError() }
        let key = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: Data(request.code.utf8)), salt: challenge,
                                         info: Self.protocolInfo, outputByteCount: 32)
        let nonce = AES.GCM.Nonce()
        let plaintext = try JSONSerialization.data(withJSONObject: ["ssid": request.ssid, "password": request.password])
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce, authenticating: challenge)
        let envelope: [String: Any] = [
            "v": 1,
            "challenge": challenge.map { String(format: "%02x", $0) }.joined(),
            "nonce": Data(nonce).base64EncodedString(),
            "ciphertext": (sealed.ciphertext + sealed.tag).base64EncodedString(),
        ]
        let encoded = try JSONSerialization.data(withJSONObject: envelope).base64EncodedString()
        let payload = Array(encoded)
        let parts = stride(from: 0, to: payload.count, by: 120).map { String(payload[$0..<min($0 + 120, payload.count)]) }
        return parts.enumerated().map { index, part in Data("\(index)/\(parts.count):\(part)".utf8) }
    }

    private func fail(_ message: String) { finish(.failure(PlatformError(message))) }

    private func finish(_ outcome: Result<String?, Error>) {
        let continuation = completion
        completion = nil
        timeout?.cancel()
        timeout = nil
        central?.stopScan()
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        peripheral?.delegate = nil
        central?.delegate = nil
        central = nil
        peripheral = nil
        characteristics = [:]
        chunks = []
        nextChunk = 0
        pairingCode = nil
        request = nil
        continuation?.resume(with: outcome)
    }
}
