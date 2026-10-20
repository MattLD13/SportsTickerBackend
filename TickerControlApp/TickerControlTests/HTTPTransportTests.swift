import Foundation
import XCTest
@testable import TickerControlState

private final class ContractURLProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        if request.url?.path == "/wait" { return }
        if request.url?.path == "/error" {
            client?.urlProtocol(self, didFailWithError: URLError(.timedOut))
            return
        }
        let status = request.url?.path == "/failure" ? 503 : 200
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: nil)!
        let fields = [
            "method": request.httpMethod ?? "",
            "authorization": request.value(forHTTPHeaderField: "Authorization") ?? "",
            "contentType": request.value(forHTTPHeaderField: "Content-Type") ?? "",
        ]
        let data = try! JSONSerialization.data(withJSONObject: fields)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class HTTPTransportTests: XCTestCase {
    func testSettingsEncoderRejectsInvalidNumbersBeforeFoundationWritesJSON() throws {
        XCTAssertThrowsError(try TickerHTTPClient.jsonData(["display_settings": ["scroll_speed": Double.nan]]))
        XCTAssertThrowsError(try TickerHTTPClient.jsonData(["display_settings": ["brightness": Double.infinity]]))
        let data = try TickerHTTPClient.jsonData(["spotify_account_id": NSNull()])
        let value = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        XCTAssertTrue(value["spotify_account_id"] is NSNull)
    }
    func testResponsePolicyRequiresExpectedHTTPStatus() {
        let url = URL(string: "https://ticker.example")!
        let accepted = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
        let rejected = HTTPURLResponse(url: url, statusCode: 403, httpVersion: nil, headerFields: nil)!
        let data = Data(#"{"error":{"message":"Pair this ticker again."}}"#.utf8)
        XCTAssertNil(TickerHTTPClient.failureMessage(data: nil, response: accepted, error: nil))
        XCTAssertEqual(TickerHTTPClient.failureMessage(data: data, response: rejected, error: nil),
                       "The server rejected the request (HTTP 403). Pair this ticker again.")
        XCTAssertNotNil(TickerHTTPClient.failureMessage(data: nil, response: accepted, error: nil, expectedStatus: 201))
        XCTAssertNotNil(TickerHTTPClient.failureMessage(data: nil, response: nil, error: nil))
    }

    func testNetworkFailureCannotBecomeSuccessfulSave() {
        let response = HTTPURLResponse(url: URL(string: "https://ticker.example")!, statusCode: 200,
                                       httpVersion: nil, headerFields: nil)!
        XCTAssertNotNil(TickerHTTPClient.failureMessage(data: nil, response: response, error: URLError(.timedOut)))
        XCTAssertNotNil(TickerHTTPClient.failureMessage(data: nil, response: response, error: URLError(.cancelled)))
    }

    func testServerErrorUsesBoundedStructuredMessage() {
        XCTAssertNil(TickerHTTPClient.serverMessage(Data("<html>bad gateway</html>".utf8)))
        XCTAssertNil(TickerHTTPClient.serverMessage(Data(#"{"error":{"message":"  "}}"#.utf8)))
        let data = try! JSONSerialization.data(withJSONObject: ["error": ["message": String(repeating: "x", count: 500)]])
        XCTAssertEqual(TickerHTTPClient.serverMessage(data)?.count, 200)
    }

    private func client() -> TickerHTTPClient {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ContractURLProtocol.self]
        return TickerHTTPClient(session: URLSession(configuration: configuration))
    }

    func testAuthorizationRequestPreservesBodyAndDefaults() {
        let url = URL(string: "https://ticker.example/api/v2/tickers/one")!
        var request = TickerHTTPClient.authorizedRequest(url: url, method: "PATCH", token: "test-token")
        request.httpBody = Data("{\"mode\":\"sports\"}".utf8)
        XCTAssertEqual(request.url, url)
        XCTAssertEqual(request.httpMethod, "PATCH")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        XCTAssertEqual(request.timeoutInterval, URLRequest(url: url).timeoutInterval)
        XCTAssertEqual(request.cachePolicy, URLRequest(url: url).cachePolicy)
        XCTAssertEqual(request.httpBody, Data("{\"mode\":\"sports\"}".utf8))
    }

    func testTaskStartsSuspendedAndForwardsAuthorizedRequest() {
        let completed = expectation(description: "request completes after resume")
        var request = TickerHTTPClient.authorizedRequest(
            url: URL(string: "https://ticker.example/api/v2/tickers/one")!, method: "PATCH", token: "test-token"
        )
        request.httpBody = Data("{\"mode\":\"sports\"}".utf8)
        request.timeoutInterval = 15
        let task = client().dataTask(with: request) { data, response, error in
            XCTAssertNil(error)
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
            let fields = try? JSONSerialization.jsonObject(with: data!) as? [String: String]
            XCTAssertEqual(fields?["method"], "PATCH")
            XCTAssertEqual(fields?["authorization"], "Bearer test-token")
            XCTAssertEqual(fields?["contentType"], "application/json")
            completed.fulfill()
        }
        XCTAssertEqual((task as? URLSessionDataTask)?.state, .suspended)
        XCTAssertEqual((task as? URLSessionDataTask)?.originalRequest?.httpBody, request.httpBody)
        XCTAssertEqual((task as? URLSessionDataTask)?.originalRequest?.timeoutInterval, 15)
        task.resume()
        wait(for: [completed], timeout: 3)
    }

    func testCancellationReachesURLSession() {
        let completed = expectation(description: "cancelled request")
        let task = client().dataTask(with: URL(string: "https://ticker.example/wait")!) { _, _, error in
            XCTAssertEqual((error as? URLError)?.code, .cancelled)
            completed.fulfill()
        }
        task.resume()
        task.cancel()
        wait(for: [completed], timeout: 3)
    }

    func testHTTPFailureReachesExistingResponsePolicy() {
        let completed = expectation(description: "HTTP status remains visible")
        let task = client().dataTask(with: URL(string: "https://ticker.example/failure")!) { data, response, error in
            XCTAssertNil(error)
            XCTAssertNotNil(data)
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 503)
            completed.fulfill()
        }
        task.resume()
        wait(for: [completed], timeout: 3)
    }

    func testNetworkErrorReachesExistingRetryPolicy() {
        let completed = expectation(description: "network error remains visible")
        let task = client().dataTask(with: URL(string: "https://ticker.example/error")!) { _, _, error in
            XCTAssertEqual((error as? URLError)?.code, .timedOut)
            completed.fulfill()
        }
        task.resume()
        wait(for: [completed], timeout: 3)
    }
}
