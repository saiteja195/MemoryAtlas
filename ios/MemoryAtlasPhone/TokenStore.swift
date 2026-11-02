import Foundation
import Security

enum TokenStore {
    private static let service = "MemoryAtlas.phone-gateway"
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: "access-token"]
    }

    static func read() -> String {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }

    static func save(_ token: String) throws {
        var request = query
        request[kSecValueData as String] = Data(token.utf8)
        request[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(request as CFDictionary, nil)
        let final = status == errSecDuplicateItem
            ? SecItemUpdate(query as CFDictionary, [kSecValueData as String: Data(token.utf8)] as CFDictionary)
            : status
        guard final == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(final),
                          userInfo: [NSLocalizedDescriptionKey: "Could not save the phone token in Keychain."])
        }
    }
}
