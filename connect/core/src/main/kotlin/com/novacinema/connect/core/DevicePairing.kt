package com.novacinema.connect.core

import java.net.URI
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.io.ByteArrayInputStream

/** Public trust material imported and explicitly confirmed by the owner, not a login token. */
class ServerTrust private constructor(val origin: String, val serverId: String, certificateDer: ByteArray, stored: Boolean) {
    constructor(origin: String, serverId: String, certificateDer: ByteArray):this(origin,serverId,certificateDer,false)
    private val certificateBytes = certificateDer.copyOf()
    val certificateDer: ByteArray get() = certificateBytes.copyOf()
    init {
        require(validOrigin(origin)) { "Invalid private HTTPS origin" }
        require(validId(serverId)) { "Invalid server identity" }
        require(certificateBytes.size in 128..8192) { "Invalid certificate size" }
        if(!stored)certificate().checkValidity() else certificate()
    }
    fun certificate(): X509Certificate = CertificateFactory.getInstance("X.509")
        .generateCertificate(ByteArrayInputStream(certificateBytes)) as X509Certificate
    override fun toString() = "ServerTrust(public identity)"
    companion object {
        // Only authenticated local storage uses this; network TLS still checks certificate dates.
        fun restore(origin:String,serverId:String,certificateDer:ByteArray)=ServerTrust(origin,serverId,certificateDer,true)
        fun validId(value: String) = value.matches(Regex("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"))
        fun validOrigin(value: String): Boolean = runCatching {
            val uri = URI(value)
            val host = uri.host ?: return false
            val octets = host.split('.').map { it.toIntOrNull() ?: return false }
            uri.scheme == "https" && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null &&
                uri.rawPath.isNullOrEmpty() && uri.port in 1..65535 && octets.size == 4 &&
                octets.all { it in 0..255 } && octets.joinToString(".") == host &&
                (host == "127.0.0.1" || RouteGuard.isPrivateGatewayHost(host))
        }.getOrDefault(false)
        fun fingerprint(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 255) }
    }
}

class DeviceGrant(val secret: String, val userCode: String, val serverId: String, val expiresIn: Int, val interval: Int) {
    init {
        require(validToken(secret) && userCode.matches(Regex("[A-Z2-9]{4}-[A-Z2-9]{4}")))
        require(ServerTrust.validId(serverId) && expiresIn in 1..600 && interval in 5..60)
    }
    override fun toString() = "DeviceGrant(redacted)"
}

class DeviceTokens(val access: String, val refresh: String, val deviceId: String, val expiresIn: Int, val refreshExpiresIn: Int) {
    init {
        require(validToken(access) && validToken(refresh) && access != refresh && ServerTrust.validId(deviceId))
        require(expiresIn in 1..300 && refreshExpiresIn in expiresIn..(30 * 86400))
    }
    override fun toString() = "DeviceTokens(redacted)"
}

fun validToken(value: String) = value.matches(Regex("[A-Za-z0-9_-]{40,128}"))
data class DeviceIdentity(val serverId: String, val deviceId: String, val origin: String, val accountId:String?=null)
class DeviceApiFailure(val status: Int, val code: String, val retryAfter: Int = 0) : Exception("Device request refused")
class DeviceProtocolFailure : Exception("Device response invalid")

interface DeviceTransport {
    fun authorize(label: String): DeviceGrant
    fun authorizeBound(label:String,assertion:String):DeviceGrant=throw DeviceProtocolFailure()
    fun poll(secret: String): DeviceTokens
    fun refresh(secret: String): DeviceTokens
    fun identity(access: String): DeviceIdentity
    fun logout(access: String)
}

class SavedDevice(val trust: ServerTrust, val tokens: DeviceTokens, val refreshDeadline: Long,
                  val refreshPending: Boolean = false, val accountId:String?=null) {
    override fun toString() = "SavedDevice(redacted)"
}
interface DeviceVault {
    fun load(): SavedDevice?
    fun save(value: SavedDevice)
    fun clear()
}

enum class PairingState { EMPTY, WAITING, ASSOCIATED, OFFLINE, EXPIRED, DENIED, REASSOCIATE, SECURITY_ERROR }
data class PairingView(val state: PairingState, val userCode: String? = null, val nextPollMillis: Long = 0)

/** One process-owned instance. Serialize refresh; persist an intent before sending it.
 * An interrupted/ambiguous rotation cannot replay a consumed refresh after process death.
 */
class DevicePairing(private val vault: DeviceVault, private val transport: (ServerTrust) -> DeviceTransport,
                    private val clock: () -> Long = System::currentTimeMillis) {
    private class Pending(val trust: ServerTrust, val grant: DeviceGrant, val deadline: Long, val accountId:String?,
                          var interval: Int, var nextPoll: Long)
    private var pending: Pending? = null

    @Synchronized fun begin(trust: ServerTrust, label: String, assertion:String?=null, accountId:String?=null): PairingView {
        require(label.isNotBlank() && label.length <= 64 && label.none { it.isISOControl() })
        require(vault.load() == null) { "Forget the existing association first" }
        pending = null
        require((assertion==null && accountId==null) || (assertion!=null && accountId!=null && ServerTrust.validId(accountId)))
        val client=transport(trust)
        val grant = if(assertion==null)client.authorize(label) else client.authorizeBound(label,assertion)
        if (grant.serverId != trust.serverId) throw DeviceProtocolFailure()
        val now = clock()
        pending = Pending(trust, grant, now + grant.expiresIn * 1000L, accountId, grant.interval, now + grant.interval * 1000L)
        return waiting(pending!!)
    }

    @Synchronized fun cancel() { pending = null }
    @Synchronized fun resume(): PairingView = pending?.let { waiting(it) } ?: check()
    private fun waiting(p: Pending) = PairingView(PairingState.WAITING, p.grant.userCode, p.nextPoll)

    @Synchronized fun poll(): PairingView {
        val p = pending ?: return PairingView(PairingState.EMPTY)
        val now = clock()
        if (now >= p.deadline) { pending = null; return PairingView(PairingState.EXPIRED) }
        if (now < p.nextPoll) return waiting(p)
        try {
            val tokens = transport(p.trust).poll(p.grant.secret)
            pending = null
            // Save immediately after a single-use exchange, then validate the protected descriptor.
            vault.save(SavedDevice(p.trust, tokens, clock() + tokens.refreshExpiresIn * 1000L,accountId=p.accountId))
            return check()
        } catch (failure: DeviceApiFailure) {
            if (failure.code == "authorization_pending" || failure.code == "slow_down") {
                if (failure.code == "slow_down") p.interval = minOf(600, p.interval + 5)
                p.interval = maxOf(p.interval, failure.retryAfter.coerceIn(0, 600))
                p.nextPoll = clock() + p.interval * 1000L
                return waiting(p)
            }
            pending = null
            return PairingView(if (failure.code == "access_denied") PairingState.DENIED else PairingState.EXPIRED)
        } catch (_: Exception) {
            // Poll may have consumed the grant. Never claim success or replay blindly.
            pending = null
            return PairingView(PairingState.REASSOCIATE)
        }
    }

    private fun verified(saved: SavedDevice): PairingView {
        val identity = transport(saved.trust).identity(saved.tokens.access)
        if (identity.serverId != saved.trust.serverId || identity.deviceId != saved.tokens.deviceId ||
            identity.origin != saved.trust.origin || (saved.accountId!=null && identity.accountId!=saved.accountId)) throw DeviceProtocolFailure()
        return PairingView(PairingState.ASSOCIATED)
    }

    @Synchronized fun check(): PairingView {
        val saved = vault.load() ?: return PairingView(PairingState.EMPTY)
        if (saved.refreshPending || clock() >= saved.refreshDeadline) {
            vault.clear(); return PairingView(PairingState.REASSOCIATE)
        }
        try {
            return verified(saved)
        } catch (error: DeviceApiFailure) {
            if (error.status != 401) return PairingView(PairingState.OFFLINE)
        } catch (_: DeviceProtocolFailure) {
            vault.clear(); return PairingView(PairingState.SECURITY_ERROR)
        } catch (_: javax.net.ssl.SSLException) {
            return PairingView(PairingState.SECURITY_ERROR)
        } catch (_: java.security.cert.CertificateException) {
            return PairingView(PairingState.SECURITY_ERROR)
        } catch (_: Exception) {
            return PairingView(PairingState.OFFLINE)
        }
        // A durable marker is written before the refresh leaves this process.
        vault.save(SavedDevice(saved.trust, saved.tokens, saved.refreshDeadline, refreshPending = true,accountId=saved.accountId))
        val renewed: SavedDevice
        try {
            val tokens = transport(saved.trust).refresh(saved.tokens.refresh)
            if (tokens.deviceId != saved.tokens.deviceId || tokens.refresh == saved.tokens.refresh ||
                tokens.access == saved.tokens.access) throw DeviceProtocolFailure()
            renewed = SavedDevice(saved.trust, tokens,
                minOf(saved.refreshDeadline, clock() + tokens.refreshExpiresIn * 1000L),accountId=saved.accountId)
            vault.save(renewed)
        } catch (_: Exception) {
            vault.clear(); return PairingView(PairingState.REASSOCIATE)
        }
        return try { verified(renewed) }
        catch (_: DeviceProtocolFailure) { vault.clear(); PairingView(PairingState.SECURITY_ERROR) }
        catch (error: DeviceApiFailure) {
            if (error.status == 401) { vault.clear(); PairingView(PairingState.REASSOCIATE) }
            else PairingView(PairingState.OFFLINE)
        } catch (_: javax.net.ssl.SSLException) { PairingView(PairingState.SECURITY_ERROR) }
        catch (_: java.security.cert.CertificateException) { PairingView(PairingState.SECURITY_ERROR) }
        catch (_: Exception) { PairingView(PairingState.OFFLINE) }
    }

    @Synchronized fun forget() {
        pending = null
        val saved = vault.load()
        // Erase locally even if the server is offline. Owner can revoke remotely in Control.
        vault.clear()
        if (saved != null && !saved.refreshPending) runCatching { transport(saved.trust).logout(saved.tokens.access) }
    }

    @Synchronized fun updateTrust(trust:ServerTrust,accountId:String) {
        val saved=vault.load() ?: throw DeviceProtocolFailure()
        require(saved.accountId==accountId && saved.trust.serverId==trust.serverId && saved.trust.origin==trust.origin)
        trust.certificate().checkValidity()
        vault.save(SavedDevice(trust,saved.tokens,saved.refreshDeadline,saved.refreshPending,saved.accountId))
    }
}
