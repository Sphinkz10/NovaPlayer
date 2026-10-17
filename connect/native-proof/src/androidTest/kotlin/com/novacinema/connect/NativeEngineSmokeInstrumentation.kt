package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.os.Build
import android.os.Bundle
import com.wireguard.android.backend.GoBackend

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
            fun loadWireGuard() {
                wireguard = GoBackend(targetContext)
                check(wireguard!!.version.isNotBlank()) { "Empty WireGuard native version" }
            }
            fun loadCombined() {
                val loader = targetContext.classLoader
                Class.forName("go.Seq", true, loader)
                Class.forName("com.novacinema.engines.libtailscale.Libtailscale", true, loader)
                Class.forName("com.novacinema.engines.android.Android", true, loader)
            }
            if (order == "wireguard-first") {
                loadWireGuard()
                loadCombined()
            } else {
                loadCombined()
                loadWireGuard()
            }
            // A second JNI call after both Go runtimes have initialized.
            val version = wireguard!!.version
            check(version.isNotBlank())
            result.putString("nova_native_smoke", "passed")
            result.putString("order", order)
            result.putString("wireguard_version", version)
            result.putInt("api", Build.VERSION.SDK_INT)
            result.putString("abis", Build.SUPPORTED_ABIS.joinToString(","))
            finish(Activity.RESULT_OK, result)
        } catch (failure: Throwable) {
            result.putString("nova_native_smoke", "failed")
            result.putString("failure", failure.stackTraceToString())
            finish(Activity.RESULT_CANCELED, result)
        }
    }
}
