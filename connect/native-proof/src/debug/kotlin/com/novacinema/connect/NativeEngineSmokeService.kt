package com.novacinema.connect

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.Process

/** Debug proof only: keep gomobile's Go runtime out of the WireGuard process. */
class NativeEngineSmokeService : Service() {
    private val messenger = Messenger(Handler(Looper.getMainLooper()) { request ->
        if (request.what != 1 || request.replyTo == null) return@Handler true
        val result = Bundle()
        try {
            val seq = Class.forName("go.Seq", true, classLoader)
            seq.getMethod("setContext", android.content.Context::class.java).invoke(null, applicationContext)
            Class.forName("com.novacinema.engines.libtailscale.Libtailscale", true, classLoader)
            Class.forName("com.novacinema.engines.android.Android", true, classLoader)
            result.putString("result", "passed")
            result.putInt("pid", Process.myPid())
        } catch (failure: Throwable) {
            result.putString("result", "failed")
            result.putString("failure", failure.stackTraceToString())
        }
        runCatching { request.replyTo.send(Message.obtain().apply { data = result }) }
        true
    })

    override fun onBind(intent: Intent) = messenger.binder
}
