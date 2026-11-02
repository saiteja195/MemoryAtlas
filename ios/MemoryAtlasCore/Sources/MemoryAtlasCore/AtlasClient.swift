import Foundation

public enum AtlasError: LocalizedError {
    case configuration(String)
    case server(Int, String)
    public var errorDescription: String? {
        switch self {
        case .configuration(let message): return message
        case .server(let code, let message): return "Backend (\(code)): \(message)"
        }
    }
}

public struct AtlasSession: Codable, Sendable {
    public let sessionID: String
    public let grantID: String
    public let revocationToken: String
    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id", grantID = "grant_id", revocationToken = "revocation_token"
    }
}

public struct StoredPhoto: Codable, Sendable {
    public let status: String
    public let sourceID: String
    public let claims: Int
    public let observation: String
    public let eventTime: String
    public let rawMediaBytesRetained: Int
    enum CodingKeys: String, CodingKey {
        case status, claims, observation
        case sourceID = "source_id", eventTime = "event_time"
        case rawMediaBytesRetained = "raw_media_bytes_retained"
    }
}

private final class NoRedirect: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

/// Photos travel in an ephemeral request body, never a URL, file or background upload queue.
public struct AtlasClient: Sendable {
    public let baseURL: URL
    private let token: String
    private let session: URLSession

    public init(baseURL: String, token: String, session: URLSession? = nil) throws {
        self.baseURL = try Self.validateURL(baseURL)
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 32, !trimmed.contains(where: { $0.isWhitespace }) else {
            throw AtlasError.configuration("Enter the phone access token from the Mac’s .env (at least 32 characters).")
        }
        self.token = trimmed
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.httpShouldSetCookies = false
        config.timeoutIntervalForRequest = 90
        config.timeoutIntervalForResource = 120
        self.session = session ?? URLSession(configuration: config, delegate: NoRedirect(), delegateQueue: nil)
    }

    public static func validateURL(_ value: String) throws -> URL {
        guard let parts = URLComponents(string: value.trimmingCharacters(in: .whitespacesAndNewlines)),
              let url = parts.url, let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/", ["http", "https"].contains(parts.scheme) else {
            throw AtlasError.configuration("Use the gateway address only, for example http://your-mac.local:8001 (no path or credentials).")
        }
        if parts.scheme == "http" && !isLocalHost(host) {
            throw AtlasError.configuration("HTTP is allowed only on a trusted local network. Use HTTPS for a remote backend.")
        }
        return url
    }

    private static func isLocalHost(_ host: String) -> Bool {
        let host = host.lowercased()
        if ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host) || host.hasSuffix(".local") { return true }
        let labels = host.split(separator: ".", omittingEmptySubsequences: false)
        let parts = labels.compactMap { Int($0) }
        guard labels.count == 4, parts.count == 4, parts.allSatisfy({ 0...255 ~= $0 }) else { return false }
        return parts[0] == 10 || (parts[0] == 192 && parts[1] == 168)
            || (parts[0] == 172 && 16...31 ~= parts[1])
    }

    func request(_ path: String, method: String = "GET", body: Data? = nil) -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        return request
    }

    private func send<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else {
            throw AtlasError.configuration("The backend did not return an HTTP response.")
        }
        guard 200..<300 ~= response.statusCode else {
            let detail = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let message = detail?["detail"] as? String ?? "Request rejected. Check the backend and try again."
            throw AtlasError.server(response.statusCode, message)
        }
        return try JSONDecoder().decode(type, from: data)
    }

    public func checkConnection() async throws {
        struct Health: Decodable { let status: String; let llm_mode: String }
        let health = try await send(request("mobile/health"), as: Health.self)
        guard health.status == "ok", health.llm_mode == "live" else {
            throw AtlasError.configuration("Switch the backend to live mode before sending real photos.")
        }
    }

    public func startSession() async throws -> AtlasSession {
        try await send(request("mobile/sessions", method: "POST"), as: AtlasSession.self)
    }

    public func upload(jpeg: Data, capturedAt: Date, sessionID: String) async throws -> StoredPhoto {
        guard !jpeg.isEmpty, jpeg.count <= 2 * 1024 * 1024 else {
            throw AtlasError.configuration("The photo must be a JPEG smaller than 2 MiB.")
        }
        let body = try Self.photoBody(jpeg: jpeg, capturedAt: capturedAt, sessionID: sessionID)
        let result = try await send(request("mobile/photos", method: "POST", body: body), as: StoredPhoto.self)
        guard result.status == "stored", result.claims > 0, result.rawMediaBytesRetained == 0 else {
            throw AtlasError.configuration("The backend did not confirm a compiled memory. Check the Atlas before retrying.")
        }
        return result
    }

    static func photoBody(jpeg: Data, capturedAt: Date, sessionID: String) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "session_id": sessionID,
            "captured_at": ISO8601DateFormatter().string(from: capturedAt),
            "image_b64": jpeg.base64EncodedString(),
        ], options: [.sortedKeys])
    }
}
