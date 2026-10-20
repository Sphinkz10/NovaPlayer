package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.os.SystemClock
import android.widget.Button
import android.view.ViewGroup
import com.novacinema.connect.core.*
import org.conscrypt.Conscrypt
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.Socket
import java.net.URL
import java.security.cert.CertificateFactory
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLException

/** Test APK only: real GoBackend, Android VPN consent, pinned TLS and device API. */
class WireGuardNetworkInstrumentation : Instrumentation() {
    private var mode = ""
    private val checks = mutableListOf<String>()
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments); mode = arguments?.getString("mode").orEmpty(); start()
    }
    private fun waitFor(action: () -> Boolean) {
        val end = SystemClock.elapsedRealtime() + 45000
        while (!action()) { check(SystemClock.elapsedRealtime() < end); Thread.sleep(100) }
    }
    private fun stage(name: String) {
        sendStatus(1, Bundle().apply { putString("wireguard_stage", name) })
    }
    private fun gate(name: String) = waitFor {
        File(targetContext.filesDir, "wireguard-gate.txt").let { it.exists() && it.readText() == name }
    }
    private fun networkRefused(action: () -> Unit) {
        var blocked = false
        try { action() } catch (_: IOException) { blocked = true }
        check(blocked)
    }
    private fun noTcp(host: String, port: Int) = networkRefused {
        Socket().use { it.connect(InetSocketAddress(host, port), 1800) }
    }
    private fun association(fixture: JSONObject): SavedDevice {
        val cert = CertificateFactory.getInstance("X.509")
            .generateCertificate(fixture.string("certificate_pem").byteInputStream())
        return SavedDevice(ServerTrust(fixture.string("enrollment_origin"), fixture.string("server_id"), cert.encoded),
            DeviceTokens(fixture.string("access_token"), fixture.string("refresh_token"), fixture.string("device_id"),300,2592000),
            System.currentTimeMillis()+2592000_000L)
    }
    override fun onStart() {
        val report = Bundle()
        var bridge: WireGuardBridge? = null
        try {
            val raw = File(targetContext.filesDir, "wireguard-fixture.json").readText()
            val fixture = JSONObject(raw)
            val vault = ProvisioningStore(targetContext)
            val enrollmentKeys = WireGuardEnrollmentStore(targetContext)
            val saved = association(fixture)
            if (mode == "restart") {
                check(vault.load()?.expectedServerId == fixture.string("server_id"))
                check(VpnService.prepare(targetContext) == null)
                checks.add("encrypted profile survives process restart")
                val localPublic = enrollmentKeys.publicKey(saved)
                val parsed = com.wireguard.config.Config.parse(vault.load()!!.config.byteInputStream())
                check(localPublic == parsed.`interface`.keyPair.publicKey.toBase64())
                checks.add("Android-generated enrollment key survives process restart")
                val enrollmentPrefs = targetContext.getSharedPreferences("nova_wireguard_enrollment", 0)
                val original = enrollmentPrefs.getString("sealed", null)!!
                val damaged = android.util.Base64.decode(original, android.util.Base64.NO_WRAP)
                damaged[damaged.lastIndex] = (damaged.last().toInt() xor 1).toByte()
                check(enrollmentPrefs.edit().putString("sealed", android.util.Base64.encodeToString(damaged, android.util.Base64.NO_WRAP)).commit())
                check(runCatching { enrollmentKeys.publicKey(saved) }.isFailure)
                check(enrollmentPrefs.getString("sealed", null) != original)
                checks.add("enrollment tampering fails closed without replacing key")
                check(enrollmentPrefs.edit().putString("sealed", original).commit())
                val keyStore = java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                keyStore.deleteEntry("nova-wireguard-enrollment-v1")
                check(runCatching { enrollmentKeys.publicKey(saved) }.isFailure)
                check(!keyStore.containsAlias("nova-wireguard-enrollment-v1"))
                checks.add("missing wrapping key never regenerates enrollment identity")
                DeviceSessionStore(targetContext).clear()
                check(enrollmentPrefs.all.isEmpty())
                checks.add("forgetting NOVA association erases local WireGuard enrollment")
                val prefs = targetContext.getSharedPreferences("nova_connect_secure", 0)
                val sealed = android.util.Base64.decode(prefs.getString("sealed", null), android.util.Base64.NO_WRAP)
                sealed[sealed.lastIndex] = (sealed.last().toInt() xor 1).toByte()
                check(prefs.edit().putString("sealed", android.util.Base64.encodeToString(sealed, android.util.Base64.NO_WRAP)).commit())
                check(vault.load() == null)
                checks.add("tampered encrypted profile fails closed")
                vault.revokeLocal(); check(vault.load() == null)
                checks.add("local profile revocation removes decryption material")
            } else {
                check(mode == "network")
                val origin = fixture.string("origin")
                val cert = CertificateFactory.getInstance("X.509")
                    .generateCertificate(fixture.string("certificate_pem").byteInputStream())
                val trust = ServerTrust(origin, fixture.string("server_id"), cert.encoded)
                val client = DeviceClient(trust)
                val access = fixture.string("access_token")
                networkRefused { client.identity(access) }
                checks.add("private service unreachable before VPN")
                val publicKey = enrollmentKeys.publicKey(saved)
                check(publicKey == WireGuardEnrollmentStore(targetContext).publicKey(saved))
                val enrollClient = DeviceClient(saved.trust)
                check(enrollClient.enrollWireGuard(saved, publicKey) == "pending")
                check(enrollClient.enrollWireGuard(saved, publicKey) == "pending")
                checks.add("Android-generated public key enrolled idempotently over pinned LAN HTTPS")
                val foreign = SavedDevice(saved.trust, DeviceTokens(saved.tokens.access, saved.tokens.refresh,
                    java.util.UUID.randomUUID().toString(),300,2592000), saved.refreshDeadline)
                check(runCatching { enrollmentKeys.publicKey(foreign) }.isFailure)
                checks.add("encrypted enrollment key bound to NOVA server origin and device")
                stage("enrolled"); gate("approved")
                check(enrollClient.wireGuardStatus(saved, publicKey) == "approved")
                checks.add("owner approval checked before constructing local lab tunnel profile")
                val localConfig = "[Interface]\nPrivateKey = ${enrollmentKeys.keys(saved).privateKey.toBase64()}\n" +
                    "Address = 10.222.0.2/32\nMTU = 1280\nIncludedApplications = ${targetContext.packageName}\n\n" +
                    "[Peer]\nPublicKey = ${fixture.string("gateway_public_key")}\nEndpoint = 10.0.2.2:${fixture.integer("endpoint_port")}\n" +
                    "AllowedIPs = 10.222.0.1/32\nPersistentKeepalive = 25\n"
                check(!raw.contains(enrollmentKeys.keys(saved).privateKey.toBase64()))
                vault.provisionAdminOnly(localConfig, origin, trust.serverId)
                val stored = targetContext.getSharedPreferences("nova_connect_secure", 0).getString("sealed", null)!!
                val decoded = android.util.Base64.decode(stored, android.util.Base64.NO_WRAP).toString(Charsets.UTF_8)
                check(!decoded.contains("PrivateKey") && !decoded.contains(localConfig))
                check(vault.load()?.config == localConfig)
                checks.add("WireGuard profile encrypted by Android Keystore")
                check(VpnService.prepare(targetContext) != null)
                val activity = startActivitySync(Intent(targetContext, WireGuardConsentActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as WireGuardConsentActivity
                try {
                    runOnMainSync {
                        val root = activity.findViewById<ViewGroup>(android.R.id.content)
                        (root.getChildAt(0) as Button).performClick()
                    }
                    stage("consent")
                    waitFor { activity.answered }
                    check(activity.approved && VpnService.prepare(targetContext) == null)
                } finally { runOnMainSync { activity.finish() } }
                checks.add("Android system VPN consent explicitly approved")
                bridge = WireGuardBridge(targetContext)
                val config = vault.load()!!.config
                var rejected = false
                try { bridge.connect(config.replace("10.222.0.1/32", "0.0.0.0/0"), origin) }
                catch (_: IllegalArgumentException) { rejected = true }
                check(rejected && !bridge.isTunnelUp())
                rejected = false
                try { bridge.connect(config.replace(targetContext.packageName, "com.android.settings"), origin) }
                catch (_: IllegalArgumentException) { rejected = true }
                check(rejected && !bridge.isTunnelUp())
                checks.add("full-tunnel and other-application profiles rejected")
                check(bridge.connect(config, origin) && bridge.isTunnelUp())
                var identity: DeviceIdentity? = null
                waitFor {
                    try { identity = client.identity(access); true } catch (_: IOException) { false }
                }
                check(identity!!.serverId == trust.serverId && identity!!.deviceId == fixture.string("device_id") && identity!!.origin == origin)
                checks.add("authenticated NOVA device API over native WireGuard and TLS 1.3")
                val wrongCert = CertificateFactory.getInstance("X.509")
                    .generateCertificate(fixture.string("wrong_certificate_pem").byteInputStream())
                var badTls = false
                try { DeviceClient(ServerTrust(origin, trust.serverId, wrongCert.encoded)).identity(access) }
                catch (_: SSLException) { badTls = true }
                check(badTls)
                checks.add("wrong HTTPS identity rejected inside tunnel")
                val admin = URL(origin + "/api/v1/admin/connect").openConnection(Proxy.NO_PROXY) as HttpsURLConnection
                try {
                    admin.sslSocketFactory = PinnedServerTls.socketFactory(trust, Conscrypt.newProvider(), true)
                    admin.instanceFollowRedirects = false; admin.connectTimeout = 2000; admin.readTimeout = 2000
                    check(admin.responseCode == 404)
                } finally { admin.disconnect() }
                checks.add("client surface does not mount administrative routes")
                noTcp("10.222.0.1", 22); noTcp("10.222.0.1", 9443)
                noTcp("10.203.0.2", 22)
                checks.add("firewall blocks live SSH/admin canaries and underlay ingress")
                stage("connected"); gate("device-revoked")
                var revoked = false
                try { client.identity(access) } catch (e: DeviceApiFailure) { revoked = e.status == 401 }
                check(revoked && bridge.isTunnelUp())
                check(ProviderRegistry.evaluate(ProviderId.WIREGUARD, AndroidCapabilities.read(targetContext),
                    ProviderObservation(provisioned = true, consentGranted = true, tunnelUp = true,
                        privateHttpsReachable = true, serverIdentityMatches = true)) != ProviderState.CONNECTED)
                checks.add("revoked device refused even while tunnel remains UP")
                stage("device-revoked"); gate("peer-removed")
                networkRefused { client.identity(access) }
                checks.add("gateway peer removal prevents further private traffic")
                bridge.disconnect(); check(!bridge.isTunnelUp())
                networkRefused { client.identity(access) }
                checks.add("disconnect stops tunnel without public fallback")
                stage("disconnected")
            }
            report.putString("nova_wireguard", "passed")
            report.putString("checks", checks.joinToString("|"))
            report.putInt("api", android.os.Build.VERSION.SDK_INT)
            finish(Activity.RESULT_OK, report)
        } catch (error: Throwable) {
            report.putString("nova_wireguard", "failed")
            report.putString("failure_type", error.javaClass.simpleName)
            report.putString("failure_at", error.stackTrace.firstOrNull { it.className.startsWith("com.novacinema") }
                ?.let { it.className + ":" + it.lineNumber })
            finish(Activity.RESULT_CANCELED, report)
        } finally { runCatching { bridge?.disconnect() } }
    }
}
