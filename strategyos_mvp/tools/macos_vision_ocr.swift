import Foundation
import ImageIO
import Vision

if CommandLine.arguments.count < 2 {
    fputs("usage: macos_vision_ocr.swift <image-path>\n", stderr)
    exit(2)
}

let imagePath = CommandLine.arguments[1]
let imageURL = URL(fileURLWithPath: imagePath)

guard let imageSource = CGImageSourceCreateWithURL(imageURL as CFURL, nil) else {
    fputs("could not open image source: \(imagePath)\n", stderr)
    exit(3)
}

guard let cgImage = CGImageSourceCreateImageAtIndex(imageSource, 0, nil) else {
    fputs("could not create CGImage: \(imagePath)\n", stderr)
    exit(4)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["en-US"]

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
    let observations = request.results ?? []
    let lines = observations.compactMap { observation in
        observation.topCandidates(1).first?.string
    }
    print(lines.joined(separator: "\n"))
} catch {
    fputs("ocr failed: \(error)\n", stderr)
    exit(5)
}
