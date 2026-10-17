package com.novacinema.connect

import com.novacinema.connect.core.JellyfinNetworkProbe
import com.novacinema.connect.core.JellyfinProbeResult
import com.novacinema.connect.core.PublicServerInfo
import org.json.JSONObject

/** Health-only probe, not user authentication; HTTP handling is shared with the tested JVM core. */
class JellyfinHttpProbe {
    fun check(baseUrl: String, expectedServerId: String): JellyfinProbeResult {
        val pinned = JellyfinNetworkProbe({ raw ->
            val obj = JSONObject(raw)
            PublicServerInfo(
                obj.optString("Id").takeIf(String::isNotBlank),
                obj.optString("ProductName").takeIf(String::isNotBlank),
                if (obj.has("StartupWizardCompleted") && !obj.isNull("StartupWizardCompleted")) obj.getBoolean("StartupWizardCompleted") else null
            )
        }, expectedServerId = expectedServerId)
        return pinned.check(baseUrl)
    }
}
