import Foundation
import XCTest
@testable import MemoryAtlasCore

final class AtlasClientTests: XCTestCase {
    func testLocalAndHTTPSAddresses() throws {
        for value in ["http://mac.local:8001", "http://192.168.1.5:8001", "http://10.0.0.2:8001", "https://atlas.example.com"] {
            XCTAssertNoThrow(try AtlasClient.validateURL(value))
        }
    }

    func testRejectsCredentialsPathsAndPublicCleartext() {
        for value in ["http://example.com", "http://192.168.1.5.evil.com", "http://mac.local:8001/capture", "https://secret@example.com", "https://example.com?token=secret", "file:///tmp/photo"] {
            XCTAssertThrowsError(try AtlasClient.validateURL(value), value)
        }
    }

    func testTokenTravelsOnlyInHeader() throws {
        let token = String(repeating: "a", count: 32)
        let client = try AtlasClient(baseURL: "http://mac.local:8001", token: token)
        let req = client.request("mobile/sessions", method: "POST")
        XCTAssertEqual(req.url?.absoluteString, "http://mac.local:8001/mobile/sessions")
        XCTAssertEqual(req.value(forHTTPHeaderField: "Authorization"), "Bearer " + token)
        XCTAssertFalse(req.url!.absoluteString.contains(token))
        XCTAssertThrowsError(try AtlasClient(baseURL: "http://mac.local:8001", token: "short"))
    }

    func testPhotoContractContainsOriginalTimeAndBytes() throws {
        let bytes = Data([0xff, 0xd8, 0xff, 0xd9])
        let body = try AtlasClient.photoBody(jpeg: bytes, capturedAt: Date(timeIntervalSince1970: 0), sessionID: "glasses-one")
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
        XCTAssertEqual(json["captured_at"], "1970-01-01T00:00:00Z")
        XCTAssertEqual(json["session_id"], "glasses-one")
        XCTAssertEqual(Data(base64Encoded: json["image_b64"]!), bytes)
    }

    func testDecodesBackendConfirmation() throws {
        let data = Data(#"{"status":"stored","source_id":"src-one","claims":3,"observation":"A wallet","event_time":"2026-11-02T12:00:00","raw_media_bytes_retained":0}"#.utf8)
        let photo = try JSONDecoder().decode(StoredPhoto.self, from: data)
        XCTAssertEqual(photo.sourceID, "src-one")
        XCTAssertEqual(photo.claims, 3)
    }
}
