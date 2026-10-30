import Foundation
import Security

/// Stores the controller tokens and the group secret as generic passwords in the Keychain.
final class KeychainCredentials: CredentialStore {
    private func query(service: String, account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    func read(service: String, account: String) -> String? {
        var request = query(service: service, account: account)
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    func write(_ value: String, service: String, account: String) -> Bool {
        let item = query(service: service, account: account)
        let data = Data(value.utf8)
        let status = SecItemUpdate(item as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var added = item
        added[kSecValueData as String] = data
        return SecItemAdd(added as CFDictionary, nil) == errSecSuccess
    }

    func remove(service: String, account: String) {
        SecItemDelete(query(service: service, account: account) as CFDictionary)
    }
}
