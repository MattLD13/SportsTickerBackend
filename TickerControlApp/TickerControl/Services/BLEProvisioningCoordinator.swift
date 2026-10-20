import Foundation
import CoreBluetooth
import CryptoKit

/// Performs the local BLE handoff without joining a temporary phone hotspot.
final class BLEProvisioningCoordinator: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    static let serviceUUID = CBUUID(string: "8F8B0001-6E2A-4D8A-9F31-8D4B77F0B001")
    static let challengeUUID = CBUUID(string: "8F8B0002-6E2A-4D8A-9F31-8D4B77F0B001")
    static let credentialsUUID = CBUUID(string: "8F8B0003-6E2A-4D8A-9F31-8D4B77F0B001")
    static let resultUUID = CBUUID(string: "8F8B0004-6E2A-4D8A-9F31-8D4B77F0B001")
    static let pairingUUID = CBUUID(string: "8F8B0005-6E2A-4D8A-9F31-8D4B77F0B001")
    private let protocolInfo = Data("SportsTicker BLE Wi-Fi v1".utf8)
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var challengeCharacteristic: CBCharacteristic?
    private var credentialsCharacteristic: CBCharacteristic?
    private var resultCharacteristic: CBCharacteristic?
    private var pairingCharacteristic: CBCharacteristic?
    private var setupCode = ""
    private var homeSSID = ""
    private var homePassword = ""
    private var chunks: [Data] = []
    private var nextChunk = 0
    private var pendingPairingCode: String?
    private var onSuccess: ((String?) -> Void)?
    private var onFailure: ((String) -> Void)?
    private var timeout: Timer?

    func start(code: String, ssid: String, password: String, onSuccess: @escaping (String?) -> Void, onFailure: @escaping (String) -> Void) {
        reset()
        setupCode = code
        homeSSID = ssid
        homePassword = password
        self.onSuccess = onSuccess
        self.onFailure = onFailure
        central = CBCentralManager(delegate: self, queue: .main)
        timeout = Timer.scheduledTimer(withTimeInterval: 60, repeats: false) { [weak self] _ in
            self?.fail("Ticker setup timed out. Move closer, check its WIFI PIN, and try again.")
        }
    }

    func cancel() { reset() }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            if central.state == .poweredOff { fail("Turn on Bluetooth to set up the ticker.") }
            if central.state == .unauthorized { fail("Allow Bluetooth access in iPhone Settings to set up the ticker.") }
            if central.state == .unsupported { fail("This device does not support Bluetooth ticker setup.") }
            return
        }
        central.scanForPeripherals(withServices: [Self.serviceUUID], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String: Any], rssi RSSI: NSNumber) {
        self.peripheral = peripheral
        peripheral.delegate = self
        central.stopScan()
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        peripheral.discoverServices([Self.serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        fail(error?.localizedDescription ?? "The ticker could not be reached over Bluetooth.")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == Self.serviceUUID }) else {
            fail(error?.localizedDescription ?? "The ticker Bluetooth service is unavailable.")
            return
        }
        peripheral.discoverCharacteristics([Self.challengeUUID, Self.credentialsUUID, Self.resultUUID, Self.pairingUUID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil else { fail(error!.localizedDescription); return }
        challengeCharacteristic = service.characteristics?.first(where: { $0.uuid == Self.challengeUUID })
        credentialsCharacteristic = service.characteristics?.first(where: { $0.uuid == Self.credentialsUUID })
        resultCharacteristic = service.characteristics?.first(where: { $0.uuid == Self.resultUUID })
        pairingCharacteristic = service.characteristics?.first(where: { $0.uuid == Self.pairingUUID })
        guard let challengeCharacteristic, credentialsCharacteristic != nil, resultCharacteristic != nil, pairingCharacteristic != nil else {
            fail("The ticker Bluetooth setup service is incomplete.")
            return
        }
        peripheral.readValue(for: challengeCharacteristic)
        if let pairingCharacteristic { peripheral.readValue(for: pairingCharacteristic) }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let data = characteristic.value else {
            fail(error?.localizedDescription ?? "The ticker returned no Bluetooth setup response.")
            return
        }
        if characteristic.uuid == Self.pairingUUID {
            let value = String(data: data, encoding: .utf8) ?? ""
            pendingPairingCode = value == "NONE" ? nil : value
        } else if characteristic.uuid == Self.challengeUUID {
            do { chunks = try makeChunks(challenge: data); nextChunk = 0; writeNextChunk() }
            catch { fail("The ticker setup message could not be secured.") }
        } else if characteristic.uuid == Self.resultUUID {
            if String(data: data, encoding: .utf8) == "OK" { finish() }
            else { fail(String(data: data, encoding: .utf8) ?? "The ticker rejected the Wi-Fi settings.") }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil else { fail(error!.localizedDescription); return }
        nextChunk += 1
        writeNextChunk()
    }

    private func writeNextChunk() {
        guard let peripheral, let characteristic = credentialsCharacteristic else { return }
        if nextChunk < chunks.count {
            peripheral.writeValue(chunks[nextChunk], for: characteristic, type: .withResponse)
        } else if let resultCharacteristic {
            peripheral.readValue(for: resultCharacteristic)
        }
    }

    private func makeChunks(challenge: Data) throws -> [Data] {
        let key = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: Data(setupCode.utf8)), salt: challenge, info: protocolInfo, outputByteCount: 32)
        let nonce = AES.GCM.Nonce()
        let plaintext = try JSONSerialization.data(withJSONObject: ["ssid": homeSSID, "password": homePassword])
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce, authenticating: challenge)
        var encrypted = Data(sealed.ciphertext)
        encrypted.append(contentsOf: sealed.tag)
        let envelope: [String: Any] = [
            "v": 1,
            "challenge": challenge.map { String(format: "%02x", $0) }.joined(),
            "nonce": Data(nonce).base64EncodedString(),
            "ciphertext": encrypted.base64EncodedString()
        ]
        let payload = try JSONSerialization.data(withJSONObject: envelope).base64EncodedString()
        let width = 120
        let parts = stride(from: 0, to: payload.count, by: width).map { index in
            let start = payload.index(payload.startIndex, offsetBy: index)
            let end = payload.index(start, offsetBy: min(width, payload.count - index))
            return String(payload[start..<end])
        }
        return parts.enumerated().map { index, part in Data("\(index)/\(parts.count):\(part)".utf8) }
    }

    private func finish() {
        let completion = onSuccess
        let code = pendingPairingCode
        reset()
        completion?(code)
    }

    private func fail(_ message: String) {
        let completion = onFailure
        reset()
        completion?(message)
    }

    private func reset() {
        timeout?.invalidate()
        timeout = nil
        central?.stopScan()
        peripheral?.delegate = nil
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        central?.delegate = nil
        central = nil
        peripheral = nil
        challengeCharacteristic = nil
        credentialsCharacteristic = nil
        resultCharacteristic = nil
        pairingCharacteristic = nil
        pendingPairingCode = nil
        chunks = []
        nextChunk = 0
        onSuccess = nil
        onFailure = nil
        setupCode = ""
        homeSSID = ""
        homePassword = ""
    }
}
