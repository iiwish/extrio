import Foundation
import Vision

var output: [[String: Any]] = []
for path in CommandLine.arguments.dropFirst() {
  do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:])
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { observation -> [String: Any]? in
        guard let text = observation.topCandidates(1).first else { return nil }
        return ["text": text.string, "confidence": text.confidence]
    }
    output.append(["lines": lines])
  } catch {
    FileHandle.standardError.write(Data(error.localizedDescription.utf8))
    exit(1)
  }
}
let data = try JSONSerialization.data(withJSONObject: output)
FileHandle.standardOutput.write(data)
