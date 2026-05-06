package com.example.flowra_dealer_app

import android.media.AudioManager
import android.media.ToneGenerator
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity: FlutterActivity() {
    private val CHANNEL = "flowra_scan_feedback"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
                val toneGenerator = ToneGenerator(AudioManager.STREAM_MUSIC, 100)

                when (call.method) {
                    "successBeep" -> {
                        toneGenerator.startTone(ToneGenerator.TONE_PROP_ACK, 180)
                        result.success(true)
                    }
                    "errorBeep" -> {
                        toneGenerator.startTone(ToneGenerator.TONE_SUP_ERROR, 250)
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }
    }
}