import Foundation

protocol TickerHTTPTask {
    func resume()
    func cancel()
}

extension URLSessionDataTask: TickerHTTPTask {}

typealias TickerHTTPCompletion = @Sendable (Data?, URLResponse?, Error?) -> Void

protocol TickerHTTPTransport {
    func dataTask(with request: URLRequest) -> any TickerHTTPTask
    func dataTask(
        with request: URLRequest,
        completionHandler: @escaping TickerHTTPCompletion
    ) -> any TickerHTTPTask
}

extension TickerHTTPTransport {
    func dataTask(with url: URL, completionHandler: @escaping TickerHTTPCompletion) -> any TickerHTTPTask {
        dataTask(with: URLRequest(url: url), completionHandler: completionHandler)
    }

}

// The caller owns authorization selection, callbacks, and task lifetime.
final class TickerHTTPClient: TickerHTTPTransport {
    enum JSONEncodingFailure: Error { case invalidObject }
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func dataTask(with request: URLRequest) -> any TickerHTTPTask {
        session.dataTask(with: request)
    }

    func dataTask(
        with request: URLRequest,
        completionHandler: @escaping TickerHTTPCompletion
    ) -> any TickerHTTPTask {
        session.dataTask(with: request, completionHandler: completionHandler)
    }

    static func authorizedRequest(url: URL, method: String, token: String) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        return request
    }

    nonisolated static func failureMessage(
        data: Data?, response: URLResponse?, error: Error?, expectedStatus: Int = 200
    ) -> String? {
        if let error { return error.localizedDescription }
        guard let response = response as? HTTPURLResponse else {
            return "The server did not return an HTTP response."
        }
        guard response.statusCode != expectedStatus else { return nil }
        let detail = serverMessage(data)
        return "The server rejected the request (HTTP \(response.statusCode))." +
            (detail.map { " \($0)" } ?? "")
    }

    nonisolated static func jsonData(_ object: Any) throws -> Data {
        guard JSONSerialization.isValidJSONObject(object) else { throw JSONEncodingFailure.invalidObject }
        return try JSONSerialization.data(withJSONObject: object)
    }

    nonisolated static func serverMessage(_ data: Data?) -> String? {
        guard let data,
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let error = object["error"] as? [String: Any],
              let message = error["message"] as? String else { return nil }
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : String(trimmed.prefix(200))
    }
}
