import Foundation
import Vision
import CoreML
import ImageIO
let input = URL(fileURLWithPath: CommandLine.arguments[1])
do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    if #available(macOS 14.0, *) {
        for (stage, devices) in try request.supportedComputeStageDevices {
            if let cpu = devices.first(where: { if case .cpu = $0 { return true }; return false }) {
                request.setComputeDevice(cpu, for: stage)
            }
        }
    } else { request.usesCPUOnly = true }
    request.usesLanguageCorrection = false
    request.automaticallyDetectsLanguage = true
    let supported = try request.supportedRecognitionLanguages()
    request.recognitionLanguages = ["en-US", "ru-RU"].filter { supported.contains($0) }
    let handler = VNImageRequestHandler(url: input, options: [:])
    try handler.perform([request])
    let values = (request.results ?? []).compactMap { $0.topCandidates(1).first }.map { ["text": $0.string, "confidence": String($0.confidence)] }
    let data = try JSONSerialization.data(withJSONObject: ["engine":"AppleVision", "observations":values], options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch {
    FileHandle.standardError.write(Data(("local_ocr_failed: " + String(describing: error) + "\n").utf8));exit(2)
}
