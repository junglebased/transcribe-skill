// audiocap OUTDIR — record system audio (others) and microphone (me) to two WAV files
// via ScreenCaptureKit (macOS 15+). No BlackHole needed. Stops on SIGINT/SIGTERM.
// Needs Screen & System Audio Recording permission for the app that launches it.
import AVFoundation
import ScreenCaptureKit

setvbuf(stdout, nil, _IOLBF, 0)
guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: audiocap OUTDIR\n".data(using: .utf8)!); exit(2)
}
let outDir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
    var files: [SCStreamOutputType: AVAudioFile] = [:]
    let names: [SCStreamOutputType: String] = [.audio: "others.wav", .microphone: "me.wav"]
    let lock = NSLock()

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio || type == .microphone, sb.isValid,
              let desc = sb.formatDescription else { return }
        let format = AVAudioFormat(cmAudioFormatDescription: desc)
        let frames = AVAudioFrameCount(sb.numSamples)
        guard frames > 0 else { return }
        try? sb.withAudioBufferList { abl, _ in
            guard let buf = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: abl.unsafePointer) else { return }
            buf.frameLength = frames
            lock.lock(); defer { lock.unlock() }
            if files[type] == nil {
                let url = outDir.appendingPathComponent(names[type]!)
                files[type] = try? AVAudioFile(forWriting: url, settings: format.settings,
                                               commonFormat: format.commonFormat, interleaved: format.isInterleaved)
            }
            try? files[type]?.write(from: buf)
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write("stream stopped: \(error.localizedDescription)\n".data(using: .utf8)!)
        exit(1)
    }

    func close() { lock.lock(); files.removeAll(); lock.unlock() }  // AVAudioFile finalizes on deinit
}

let rec = Recorder()
var stream: SCStream?

Task {
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { throw NSError(domain: "audiocap", code: 1) }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.captureMicrophone = true
        cfg.excludesCurrentProcessAudio = true
        cfg.sampleRate = 48000
        cfg.channelCount = 1
        cfg.width = 2; cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let s = SCStream(filter: filter, configuration: cfg, delegate: rec)
        let q = DispatchQueue(label: "audiocap")
        try s.addStreamOutput(rec, type: .audio, sampleHandlerQueue: q)
        try s.addStreamOutput(rec, type: .microphone, sampleHandlerQueue: q)
        try await s.startCapture()
        stream = s
        print("recording → \(outDir.path)")
    } catch {
        FileHandle.standardError.write("capture failed: \(error.localizedDescription)\nGrant Screen & System Audio Recording to your terminal/app in System Settings → Privacy & Security.\n".data(using: .utf8)!)
        exit(1)
    }
}

func shutdown() {
    Task {
        try? await stream?.stopCapture()
        rec.close()
        print("stopped")
        exit(0)
    }
}
signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
let sigs = [SIGINT, SIGTERM].map { sig -> DispatchSourceSignal in
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { shutdown() }
    src.resume()
    return src
}
dispatchMain()
