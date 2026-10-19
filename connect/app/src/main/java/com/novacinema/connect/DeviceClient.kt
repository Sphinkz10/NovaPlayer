package com.novacinema.connect

import com.novacinema.connect.core.*
import org.json.JSONObject
import java.net.Proxy
import java.net.URL
import java.io.InputStream
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection

internal fun JSONObject.string(name: String): String = get(name) as? String ?: throw DeviceProtocolFailure()
internal fun JSONObject.integer(name: String): Int {
    val value = get(name)
    if (value !is Int) throw DeviceProtocolFailure()
    return value
}
internal fun InputStream.bounded(max: Int): ByteArray {
    val output = java.io.ByteArrayOutputStream()
    val chunk = ByteArray(2048)
    val deadline = System.nanoTime() + 15_000_000_000L
    while (true) {
        if (System.nanoTime() > deadline) throw java.io.IOException("Read deadline")
        val count = read(chunk)
        if (count < 0) break
        if (output.size() + count > max) throw DeviceProtocolFailure()
        output.write(chunk, 0, count)
    }
    return output.toByteArray()
}

/** Parsing does not confer trust: the entire file fingerprint must be confirmed before use. */
class DeviceInvitation private constructor(val trust: ServerTrust, val expiresAt: Long, val fingerprint: String) {
    fun confirm(expectedFingerprint: String, now: Long = System.currentTimeMillis()): ServerTrust {
        require(now < expiresAt && expiresAt <= now + 86400_000L) { "Invitation expired" }
        require(expectedFingerprint.matches(Regex("[a-f0-9]{64}")) &&
            java.security.MessageDigest.isEqual(expectedFingerprint.toByteArray(), fingerprint.toByteArray())) {
            "Invitation fingerprint mismatch"
        }
        trust.certificate().checkValidity()
        return trust
    }
    companion object {
        fun parse(raw: ByteArray, now: Long = System.currentTimeMillis()): DeviceInvitation {
            require(raw.size in 1..16_384)
            val json = JSONObject(String(raw, Charsets.UTF_8))
            require(json.keys().asSequence().toSet() == setOf("version", "purpose", "server_id", "client_origin", "certificate_pem", "expires_at"))
            require(json.integer("version") == 1 && json.string("purpose") == "nova-device-bootstrap")
            val seconds = json.get("expires_at")
            require(seconds is Int || seconds is Long)
            val expires = (seconds as Number).toLong()
            require(expires in (now / 1000 + 1)..(now / 1000 + 86400))
            val pem = json.string("certificate_pem")
            require(pem.matches(Regex("-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\\r\\n]+-----END CERTIFICATE-----\\s*")))
            val cert = CertificateFactory.getInstance("X.509").generateCertificate(pem.byteInputStream()) as X509Certificate
            val trust = ServerTrust(json.string("client_origin"), json.string("server_id"), cert.encoded)
            return DeviceInvitation(trust, expires * 1000, ServerTrust.fingerprint(raw))
        }
    }
}

class DeviceClient(private val trust: ServerTrust) : DeviceTransport {
    private val sockets = PinnedServerTls.socketFactory(trust)
    private fun request(path: String, body: JSONObject? = null, access: String? = null): JSONObject {
        val connection = URL(trust.origin + "/api/v1/device/" + path).openConnection(Proxy.NO_PROXY) as HttpsURLConnection
        try {
            connection.sslSocketFactory = sockets
            // Keep the platform hostname verifier. Redirects can never carry credentials elsewhere.
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 4000; connection.readTimeout = 5000
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Accept-Encoding", "identity")
            connection.setRequestProperty("Cache-Control", "no-store")
            if (access != null) {
                require(validToken(access))
                connection.setRequestProperty("Authorization", "Bearer $access")
            }
            if (body != null) {
                val bytes = body.toString().toByteArray(Charsets.UTF_8)
                require(bytes.size <= 4096)
                connection.requestMethod = "POST"; connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.setFixedLengthStreamingMode(bytes.size)
                connection.outputStream.use { it.write(bytes) }
            }
            val status = connection.responseCode
            if (status in 300..399 || connection.contentEncoding?.let { it != "identity" } == true)
                throw DeviceProtocolFailure()
            if (connection.contentType?.substringBefore(';')?.trim() != "application/json") throw DeviceProtocolFailure()
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val raw = stream?.use { it.bounded(16_384) } ?: throw DeviceProtocolFailure()
            val json = try { JSONObject(String(raw, Charsets.UTF_8)) } catch (_: Exception) { throw DeviceProtocolFailure() }
            if (status !in 200..299) {
                val error = json.optString("error", "request_refused").takeIf { it.matches(Regex("[a-z_]{1,60}")) } ?: "request_refused"
                throw DeviceApiFailure(status, error, connection.getHeaderField("Retry-After")?.toIntOrNull()?.coerceIn(0, 600) ?: 0)
            }
            return json
        } finally { connection.disconnect() }
    }
    private fun tokens(json: JSONObject): DeviceTokens {
        if (json.string("scope") != "device:read" || json.string("token_type") != "Bearer") throw DeviceProtocolFailure()
        return DeviceTokens(json.string("access_token"), json.string("refresh_token"), json.string("device_id"),
            json.integer("expires_in"), json.integer("refresh_expires_in"))
    }
    override fun authorize(label: String): DeviceGrant {
        return grant(request("authorize", JSONObject().put("label", label)))
    }
    override fun authorizeBound(label:String,assertion:String):DeviceGrant {
        require(assertion.length<=4096)
        return grant(request("authorize",JSONObject().put("label",label).put("assertion",JSONObject(assertion))))
    }
    private fun grant(json:JSONObject):DeviceGrant {
        if (json.string("scope") != "device:read") throw DeviceProtocolFailure()
        return DeviceGrant(json.string("device_code"), json.string("user_code"), json.string("server_id"),
            json.integer("expires_in"), json.integer("interval"))
    }
    override fun poll(secret: String) = tokens(request("token", JSONObject().put("device_code", secret)))
    override fun refresh(secret: String) = tokens(request("refresh", JSONObject().put("refresh_token", secret)))
    override fun identity(access: String): DeviceIdentity {
        val json = request("me", access = access)
        val descriptor = json.getJSONObject("descriptor")
        if (json.string("scope") != "device:read" || descriptor.integer("schema_version") != 1 ||
            descriptor.string("server_id") != json.string("server_id") ||
            listOf("media_enabled", "remote_access_enabled").any { descriptor.get(it) != false } ||
            descriptor.get("directory_enabled") !is Boolean)
            throw DeviceProtocolFailure()
        val account=if(json.isNull("account_id"))null else json.string("account_id").also { require(ServerTrust.validId(it)) }
        if(descriptor.getBoolean("directory_enabled")!=(account!=null))throw DeviceProtocolFailure()
        return DeviceIdentity(json.string("server_id"), json.string("device_id"), descriptor.string("client_origin"),account)
    }
    fun permissions(saved:SavedDevice):List<Pair<String,String>> {
        val data=request("libraries",access=saved.tokens.access)
        require(data.string("server_id")==trust.serverId && data.string("device_id")==saved.tokens.deviceId &&
            data.string("account_id")==saved.accountId && data.get("media_enabled")==false && data.get("catalog_enabled")==false)
        val values=data.getJSONArray("libraries");require(values.length()<=2)
        return (0 until values.length()).map { i ->
            val lib=values.getJSONObject(i);val id=lib.string("id");val name=lib.string("name")
            require(id.matches(Regex("[a-f0-9]{32}")) && name.length in 1..80 && name.none { it.isISOControl() })
            id to name
        }.also { require(it.map { lib -> lib.first }.distinct().size==it.size) }
    }
    override fun logout(access: String) { request("logout", JSONObject(), access) }
}
