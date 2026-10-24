package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Process
import com.wireguard.android.backend.GoBackend
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Loads the real JNI runtimes. Does not enroll peers or establish a tunnel. */
class NativeEngineSmokeInstrumentation : Instrumentation() {
    private var order = ""
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        order = arguments?.getString("order").orEmpty()
        start()
    }

    override fun onStart() {
        val result = Bundle()
        try {
            check(order == "wireguard-first" || order == "gomobile-first") { "Unknown load order" }
            var wireguard: GoBackend? = null
            var overlayPid = 0
            fun loadWireGuard() {
                wireguard = GoBackend(targetContext)
                check(wireguard!!.version.isNotBlank()) { "Empty WireGuard native version" }
            }
            fun loadCombined() {
                val response = loadInPrivateProcess()
                check(response.getString("result") == "passed") { response.getString("failure").orEmpty() }
                overlayPid = response.getInt("pid")
                check(overlayPid > 0 && overlayPid != Process.myPid()) { "Go runtimes must use distinct processes" }
            }
            if (order == "wireguard-first") {
                loadWireGuard()
                loadCombined()
            } else {
                loadCombined()
                loadWireGuard()
            }
            // Repeat WireGuard JNI after the overlay runtime initialized in its own process.
            val version = wireguard!!.version
            check(version.isNotBlank())
            result.putString("nova_native_smoke", "passed")
            result.putString("order", order)
            result.putString("wireguard_version", version)
            result.putInt("wireguard_pid", Process.myPid())
            result.putInt("overlay_pid", overlayPid)
            result.putInt("api", Build.VERSION.SDK_INT)
            result.putString("abis", Build.SUPPORTED_ABIS.joinToString(","))
            finish(Activity.RESULT_OK, result)
        } catch (failure: Throwable) {
            result.putString("nova_native_smoke", "failed")
            result.putString("failure", failure.stackTraceToString())
            finish(Activity.RESULT_CANCELED, result)
        }
    }

    private fun loadInPrivateProcess(): Bundle {
        val done = CountDownLatch(1)
        val response = AtomicReference<Bundle>()
        val replies = HandlerThread("native-proof-replies").apply { start() }
        val receiver = Messenger(Handler(replies.looper) { message ->
            response.set(Bundle(message.data))
            done.countDown()
            true
        })
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                Messenger(binder).send(Message.obtain(null, 1).apply { replyTo = receiver })
            }
            override fun onServiceDisconnected(name: ComponentName) {
                response.set(Bundle().apply { putString("failure", "Native service disconnected") })
                done.countDown()
            }
        }
        var bound = false
        try {
            val intent = Intent().setClassName(targetContext, "com.novacinema.connect.NativeEngineSmokeService")
            bound = targetContext.bindService(intent, connection, Context.BIND_AUTO_CREATE)
            check(bound) { "Native service could not bind" }
            check(done.await(20, TimeUnit.SECONDS)) { "Native service did not reply" }
            return checkNotNull(response.get())
        } finally {
            if (bound) targetContext.unbindService(connection)
            replies.quitSafely()
        }
    }
}
