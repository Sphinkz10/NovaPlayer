package com.novacinema.connect.core

import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import javax.net.ssl.SSLException

/** Reusable bounded transport. JSON decoder is supplied by Android (org.json) or the test fixture. */
class JellyfinNetworkProbe(
    private val decodePublicInfo: (String) -> PublicServerInfo?,
    private val openConnection: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
    private val expectedServerId: String? = null
) {
    fun check(baseUrl: String, allowLoopbackHttpForTests: Boolean = false): JellyfinProbeResult {
        val host = runCatching { java.net.URI(baseUrl).host }.getOrNull()
        val productionPrivate = EndpointValidator.isValid(baseUrl, vpn = true)
        val testLoopback = allowLoopbackHttpForTests && host in setOf("127.0.0.1", "localhost") &&
            EndpointValidator.isValid(baseUrl, vpn = false, allowLoopbackHttpForTests = true)
        require(productionPrivate || testLoopback) {
            "Only a provisioned private HTTPS endpoint is permitted"
        }
        var conn: HttpURLConnection? = null
        return try {
            val uri = EndpointValidator.publicInfoUrl(baseUrl, allowLoopbackHttpForTests)
            conn = openConnection(uri.toURL())
            conn.instanceFollowRedirects = false
            conn.connectTimeout = 4000
            conn.readTimeout = 5000
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("Cache-Control", "no-store")
            conn.requestMethod = "GET"
            val status = conn.responseCode
            val publicInfo = if (status == 200) {
                // A malformed response is NOT an offline network; fail with UNEXPECTED_RESPONSE.
                runCatching { decodePublicInfo(String(conn.inputStream.use { it.readAtMost(16_384) }, Charsets.UTF_8)) }.getOrNull()
            } else null
            val header = conn.getHeaderField("Retry-After")?.toIntOrNull()
            JellyfinHealth.evaluate(status, publicInfo, header, expectedServerId)
        } catch (_: SSLException) { JellyfinProbeResult(JellyfinStatus.TLS_VALIDATION_FAILED, false) }
          catch (_: SecurityException) { JellyfinProbeResult(JellyfinStatus.SECURITY_BLOCKED, false) }
          catch (_: Exception) { JellyfinHealth.evaluate(null) }
        finally { conn?.disconnect() }
    }

    private fun InputStream.readAtMost(max: Int): ByteArray {
        val buffer = ByteArray(max + 1)
        var size = 0
        while (size < buffer.size) {
            val n = read(buffer, size, buffer.size - size)
            if (n < 0) break
            size += n
        }
        if (size > max) throw IllegalArgumentException("Response exceeds public-info limit")
        return buffer.copyOf(size)
    }
}
