package com.novacinema.connect

import android.content.Context
import android.net.VpnService
import android.os.SystemClock
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.IOException
import java.net.URI
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/** Public parameters obtained exclusively through the already pinned device API. */
internal class RemoteWireGuardProfile private constructor(val json: String, val trust: ServerTrust,
    private val address: String, private val gatewayKey: String, private val endpoint: String,
    private val allowed: String, val expiresAt: Long) {
    fun sameTransport(other:RemoteWireGuardProfile):Boolean = address==other.address && gatewayKey==other.gatewayKey &&
        endpoint==other.endpoint && allowed==other.allowed && trust.origin==other.trust.origin &&
        trust.serverId==other.trust.serverId && trust.certificateDer.contentEquals(other.trust.certificateDer)
    fun config(context: Context, saved: SavedDevice): String {
        check(System.currentTimeMillis() < expiresAt)
        val keys = WireGuardEnrollmentStore(context).keys(saved)
        return "[Interface]\nPrivateKey = ${keys.privateKey.toBase64()}\nAddress = $address\nMTU = 1280\n" +
            "IncludedApplications = ${context.packageName}\n\n[Peer]\nPublicKey = $gatewayKey\n" +
            "Endpoint = $endpoint\nAllowedIPs = $allowed\nPersistentKeepalive = 25\n"
    }
    companion object {
        fun parse(raw: String, saved: SavedDevice, publicKey: String, now: Long = System.currentTimeMillis()): RemoteWireGuardProfile {
            require(raw.length in 1..8192)
            val data = JSONObject(raw)
            require(data.keys().asSequence().toSet() == setOf("schema_version","server_id","device_id","public_key",
                "revision","address","gateway_public_key","endpoint","client_origin","allowed_ip","issued_at","expires_at","handshake_verified"))
            require(data.integer("schema_version") == 1 && data.string("server_id") == saved.trust.serverId &&
                data.string("device_id") == saved.tokens.deviceId && data.string("public_key") == publicKey &&
                data.integer("revision") >= 2 && data.get("handshake_verified") == false)
            fun seconds(name: String): Long {
                val value = data.get(name);require(value is Int || value is Long);return (value as Number).toLong()
            }
            val issued = seconds("issued_at");val expiry = seconds("expires_at")
            // Independent NAS/TV clocks may differ slightly. Bound future skew
            // explicitly; never extend expiry or alter TLS certificate checks.
            require(issued in 1..(now/1000+30) && expiry > now/1000 && expiry-issued in 1..86400)
            val origin = data.string("client_origin")
            val host = URI(origin).host ?: error("Missing gateway")
            require(RouteGuard.isPrivateGatewayHost(host) && ServerTrust.validOrigin(origin))
            val allowed = data.string("allowed_ip");require(allowed == "$host/32")
            val address = data.string("address")
            require(address.endsWith("/32") && RouteGuard.isPrivateGatewayHost(address.removeSuffix("/32")) && address != allowed)
            val key = data.string("gateway_public_key")
            require(key.length == 44 && com.wireguard.crypto.Key.fromBase64(key).toBase64() == key && key != publicKey)
            val endpoint = data.string("endpoint")
            require(endpoint.matches(Regex("[a-z0-9][a-z0-9.-]{0,252}:[0-9]{1,5}")))
            val port = endpoint.substringAfterLast(':');require(port.toInt() in 1..65535 && port.toInt().toString() == port)
            val underlay = endpoint.substringBeforeLast(':')
            require(underlay.split('.').all { it.matches(Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")) })
            // No new certificate can be introduced by a profile. The LAN leaf
            // must also cover the gateway IP; platform hostname checks stay on.
            val trust = ServerTrust(origin,saved.trust.serverId,saved.trust.certificateDer)
            return RemoteWireGuardProfile(raw,trust,address,key,endpoint,allowed,expiry*1000)
        }
    }
}

/** One engine/operation owner across Activity recreation. No automatic LAN fallback. */
internal object RemoteWireGuardRuntime {
    private data class Route(val base: ServerTrust,val remote: ServerTrust,val device: String,val account: String?,
        val deadline: Long, val expiresAt: Long, val engine: WireGuardBridge, val profile:RemoteWireGuardProfile)
    @Volatile private var route: Route? = null
    private val operations = Any()
    private val persistence = Any()
    private val generation = AtomicLong()
    private val renewals=Executors.newSingleThreadScheduledExecutor { task -> Thread(task,"nova-profile-renewal").apply { isDaemon=true } }
    private var renewal:ScheduledFuture<*>?=null
    private fun preferences(context:Context) = context.getSharedPreferences("nova_remote_selection",Context.MODE_PRIVATE)
    fun selected(context:Context) = preferences(context).getBoolean("wireguard",false)
    fun project(context:Context,saved:SavedDevice):SavedDevice {
        if (!selected(context)) return saved
        val active=route ?: throw IOException("Connect the selected private transport")
        if (saved.trust.serverId != active.base.serverId || saved.tokens.deviceId != active.device || saved.accountId != active.account ||
            saved.trust.origin != active.base.origin || !saved.trust.certificateDer.contentEquals(active.base.certificateDer) ||
            SystemClock.elapsedRealtime() >= active.deadline || System.currentTimeMillis() >= active.expiresAt ||
            !active.engine.isTunnelUp()) throw IOException("Private transport unavailable")
        return SavedDevice(active.remote,saved.tokens,saved.refreshDeadline,saved.refreshPending,saved.accountId)
    }
    fun persistent(saved:SavedDevice):SavedDevice {
        val active=route ?: return saved
        if(saved.trust.origin!=active.remote.origin) return saved
        require(saved.trust.serverId==active.base.serverId && saved.tokens.deviceId==active.device && saved.accountId==active.account &&
            saved.trust.certificateDer.contentEquals(active.remote.certificateDer))
        return SavedDevice(active.base,saved.tokens,saved.refreshDeadline,saved.refreshPending,saved.accountId)
    }
    fun prepare(context:Context):String = synchronized(operations) {
        check(!RemoteTailscaleRuntime.selected(context))
        val operation=generation.get()
        check(!selected(context)) { "Prepare over the approved local connection" }
        check(DeviceAssociationRuntime.get(context).check().state==PairingState.ASSOCIATED)
        val saved=DeviceSessionStore(context).loadBase() ?: error("Association required")
        val keys=WireGuardEnrollmentStore(context);val client=DeviceClient(saved.trust)
        val state=client.enrollWireGuard(saved,keys.publicKey(saved))
        if(state=="approved") {
            val profile=client.wireGuardProfile(saved,keys.publicKey(saved))
            synchronized(persistence) {
                check(operation==generation.get())
                ProvisioningStore(context).saveRemote(profile.json)
            }
        }
        state
    }
    fun connect(context:Context):Boolean = synchronized(operations) {
        check(!RemoteTailscaleRuntime.selected(context))
        val operation=generation.get()
        check(VpnService.prepare(context)==null)
        val saved=DeviceSessionStore(context).loadBase() ?: error("Association required")
        val raw=ProvisioningStore(context).loadRemote() ?: error("Prepare the approved profile on the LAN")
        val profile=RemoteWireGuardProfile.parse(raw,saved,WireGuardEnrollmentStore(context).publicKey(saved))
        val bridge=route?.engine ?: WireGuardBridge(context)
        synchronized(persistence) {
            check(operation==generation.get())
            check(preferences(context).edit().putBoolean("wireguard",true).commit())
        }
        var success=false
        try {
            bridge.disconnect()
            check(operation==generation.get())
            check(bridge.connect(profile.config(context,saved),profile.trust.origin))
            route=Route(saved.trust,profile.trust,saved.tokens.deviceId,saved.accountId,
                SystemClock.elapsedRealtime()+profile.expiresAt-System.currentTimeMillis(),profile.expiresAt,bridge,profile)
            val end=SystemClock.elapsedRealtime()+15000
            do {
                check(operation==generation.get())
                val state=DeviceAssociationRuntime.get(context).check().state
                if(state==PairingState.ASSOCIATED) { success=true;break }
                if(state!=PairingState.OFFLINE) break
                Thread.sleep(200)
            } while(SystemClock.elapsedRealtime()<end)
            check(operation==generation.get())
            if(success) {
                renewal?.cancel(false)
                val app=context.applicationContext
                renewal=renewals.scheduleWithFixedDelay({ runCatching { renewIfDue(app) } },5,5,TimeUnit.MINUTES)
            }
            success
        } finally {
            if(!success || operation!=generation.get())runCatching { bridge.disconnect() }
            // Retain the route identity for a concurrent refresh save; selection
            // stays remote, so failure never silently sends tokens over LAN.
        }
    }
    private fun renewIfDue(context:Context) = synchronized(operations) {
        val active=route ?: return@synchronized
        if(selected(context) && minOf(active.expiresAt-System.currentTimeMillis(),
                active.deadline-SystemClock.elapsedRealtime())<=12*60*60*1000L) renew(context)
    }
    /** Extend only a still-valid route, over that route's pinned HTTPS API. */
    fun renew(context:Context):Boolean = synchronized(operations) {
        val operation=generation.get()
        check(selected(context))
        val active=route ?: error("Connect the selected private transport")
        check(DeviceAssociationRuntime.get(context).check().state==PairingState.ASSOCIATED)
        val base=DeviceSessionStore(context).loadBase() ?: error("Association required")
        val saved=project(context,base) // Enforces expiry, identity and live engine.
        val renewed=DeviceClient(saved.trust).wireGuardProfile(saved,WireGuardEnrollmentStore(context).publicKey(base))
        check(active.profile.sameTransport(renewed) && renewed.expiresAt>=active.expiresAt)
        check(operation==generation.get() && route===active)
        project(context,base) // A response arriving after the old deadline cannot reopen access.
        synchronized(persistence) {
            check(operation==generation.get())
            project(context,base)
            ProvisioningStore(context).saveRemote(renewed.json)
            route=active.copy(deadline=SystemClock.elapsedRealtime()+renewed.expiresAt-System.currentTimeMillis(),
                expiresAt=renewed.expiresAt,profile=renewed)
        }
        true
    }
    fun disconnectToLan(context:Context) {
        check(!RemoteTailscaleRuntime.selected(context))
        generation.incrementAndGet()
        synchronized(operations) {
            renewal?.cancel(false);renewal=null
            route?.engine?.disconnect()
            check(preferences(context).edit().putBoolean("wireguard",false).commit())
        }
    }
    fun forget(context:Context) {
        generation.incrementAndGet()
        // Called while DevicePairing holds its refresh lock: do not wait for
        // operations here. The in-flight connect observes generation and stops.
        synchronized(persistence) {
            check(preferences(context).edit().clear().commit())
            ProvisioningStore(context).clearRemote()
        }
        val engine=route?.engine
        if(engine!=null)Thread { synchronized(operations) { if(!selected(context)) {
            renewal?.cancel(false);renewal=null;runCatching { engine.disconnect() }
        } } }.start()
    }
}
