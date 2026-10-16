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
}
