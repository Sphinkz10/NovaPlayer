package com.novacinema.connect

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.net.VpnService
import android.os.*
import com.novacinema.engines.libtailscale.*
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors

/** libtailscale permits one Application per process, across VpnService instances. */
private object TailscaleEngineRuntime {
    val work = Executors.newSingleThreadExecutor()
    private var engine: com.novacinema.engines.libtailscale.Application? = null
    fun acquire(context: android.content.Context, state: TailscaleStateStore, ca: ByteArray):
        com.novacinema.engines.libtailscale.Application {
        // Called only from the shared serial worker, including service teardown.
        return engine ?: run {
            go.Seq.setContext(context)
            val directory = java.io.File(context.noBackupFilesDir, "tailscale").apply { check(mkdirs() || isDirectory) }
            Libtailscale.start(directory.path, directory.path, false, TailscalePlatform(context, state, ca)).also {
                it.setClientLoggingEnabled(false); engine = it
            }
        }
    }
}

/** Real native VPN adapter. Included only in the explicit Tailscale debug proof variant. */
class TailscaleVpnService : VpnService() {
    private val instance = UUID.randomUUID().toString()
    private val work = TailscaleEngineRuntime.work
    private var app: com.novacinema.engines.libtailscale.Application? = null
    private var gateway: String? = null
    private var registered = false
    @Volatile private var tun = false
    @Volatile private var failed = false
    private var phase = "idle"
    private var apiStatus = 0
    private val engineService = object : IPNService {
        override fun id(): String = instance
        override fun protect(fd: Int): Boolean = this@TailscaleVpnService.protect(fd)
        override fun newBuilder(): VPNServiceBuilder = restrictedBuilder(checkNotNull(gateway))
        override fun close() { disconnectVPN() }
        override fun disconnectVPN() { tun = false; failed = true }
        override fun updateVpnStatus(active: Boolean) { tun = active }
    }
    private val messages by lazy { Messenger(Handler(Looper.getMainLooper()) { message ->
        // Private component plus an explicit UID check. Never expose arbitrary LocalAPI calls.
        if (message.sendingUid != Process.myUid() || message.replyTo == null) return@Handler true
        val command = message.what; val arguments = Bundle(message.data); val reply = message.replyTo
        work.execute {
            val response = Bundle()
            try {
                when (command) {
                    1 -> connect(arguments)
                    2 -> { /* status only */ }
                    3 -> disconnect()
                    else -> error("Unsupported command")
                }
                response.putString("result", "ok")
                response.putBoolean("tun", tun)
                response.putBoolean("failed", failed)
                response.putInt("pid", Process.myPid())
                if (app != null && command != 3) {
                    val status = api("GET", "status")
                    response.putString("backend", status.optString("BackendState"))
                    response.putString("node_key", status.optJSONObject("Self")?.optString("PublicKey"))
                }
            } catch (failure: Exception) {
                // Errors from the coordinator may contain auth keys or login URLs.
                response.putString("result", "refused"); response.putBoolean("failed", true)
                response.putString("failure_stage", phase)
                response.putString("failure_type", failure.javaClass.simpleName)
                response.putInt("api_status", apiStatus)
                runCatching { disconnect() }
            }
            runCatching { reply.send(Message.obtain(null, command).apply { data = response }) }
        }; true
    }) }
    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("nova-tailscale", "NOVA Tailscale", NotificationManager.IMPORTANCE_LOW))
        startForeground(421, Notification.Builder(this, "nova-tailscale")
            .setSmallIcon(android.R.drawable.ic_lock_lock).setContentTitle("NOVA · Tailscale em ensaio")
            .setContentText("Ligação privada ao gateway NOVA").setOngoing(true).build())
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int) = START_NOT_STICKY
    override fun onBind(intent: Intent): IBinder? =
        if (intent.action == SERVICE_INTERFACE) super.onBind(intent) else messages.binder
    private fun connect(options: Bundle) {
        phase = "validate"
        check(VpnService.prepare(this) == null) { "VPN consent required" }
        val control = TailscaleRoutePolicy.controlOrigin(checkNotNull(options.getString("control")))
        val address = checkNotNull(options.getString("gateway")); TailscaleRoutePolicy(address)
        check(!registered && (gateway == null || gateway == address))
        val ca = options.getByteArray("fixture_ca") ?: byteArrayOf()
        require(ca.size <= 16384)
        phase = "state-preflight"
        val state = TailscaleStateStore(this); state.preflight()
        val binding = JSONObject().put("control", control).put("gateway", address).toString()
        val previous = state.read("nova-binding")
        require(previous.isEmpty() || previous == binding) { "Identity belongs to another gateway" }
        if (previous.isEmpty()) state.write("nova-binding", binding)
        gateway = address; failed = false
        if (app == null) {
            phase = "engine-initialize"
            app = TailscaleEngineRuntime.acquire(applicationContext, state, ca)
        }
        val prefs = JSONObject().put("ControlURL", control).put("WantRunning", true)
            .put("LoggedOut", false).put("RouteAll", false).put("CorpDNS", false)
            .put("ShieldsUp", true).put("ExitNodeID", "").put("ExitNodeIP", "")
            .put("ExitNodeAllowLANAccess", false).put("AdvertiseRoutes", org.json.JSONArray())
        val masked = JSONObject(prefs.toString())
        prefs.keys().forEach { masked.put(it + "Set", true) }
        val configured = api("PATCH", "prefs", masked)
        val start = JSONObject().put("UpdatePrefs", configured)
        val key = options.getString("auth_key").orEmpty()
        require(key.length <= 2048 && key.none { it.isWhitespace() || it.isISOControl() })
        if (key.isNotEmpty()) start.put("AuthKey", key)
        Libtailscale.requestVPN(engineService); registered = true
        api("POST", "start", start)
        if (key.isNotEmpty()) api("POST", "login-interactive")
    }
    private fun api(method: String, endpoint: String, json: JSONObject? = null): JSONObject {
        phase = endpoint; apiStatus = 0
        val body = json?.toString()?.toByteArray()?.let { bytes -> object : InputStream {
            private var sent = false
            override fun read(): ByteArray? = if (sent) null else bytes.also { sent = true }
            override fun close() { sent = true }
        } }
        val response = checkNotNull(app).callLocalAPI(15000, method, "/localapi/v0/" + endpoint, body)
        apiStatus = response.statusCode().toInt()
        check(apiStatus in 200..299)
        // Gomobile represents a zero-length Go []byte as null on this binding.
        val raw = response.bodyBytes() ?: byteArrayOf(); require(raw.size <= 2_000_000)
        return if (raw.isEmpty()) JSONObject() else JSONObject(String(raw, Charsets.UTF_8))
    }
    private fun disconnect() {
        // Closing TUN comes first even if LocalAPI/coordinator is unhealthy.
        if (registered) { Libtailscale.serviceDisconnect(engineService); registered = false }
        tun = false
        if (app != null) api("PATCH", "prefs", JSONObject().put("WantRunning", false).put("WantRunningSet", true))
    }
    override fun onRevoke() { work.execute { runCatching { disconnect() }; stopSelf() } }
    override fun onDestroy() {
        work.execute { runCatching { disconnect() } }; super.onDestroy()
    }
    private fun restrictedBuilder(address: String): VPNServiceBuilder {
        val policy = TailscaleRoutePolicy(address)
        val builder = Builder().setSession("NOVA Tailscale").addAllowedApplication(packageName)
        return object : VPNServiceBuilder {
            override fun setMTU(mtu: Int) { require(mtu in 1280..1500); builder.setMtu(mtu) }
            override fun addDNSServer(ip: String) { error("NOVA does not capture DNS") }
            override fun addSearchDomain(domain: String) { error("NOVA does not capture DNS") }
            override fun addRoute(ip: String, prefix: Int) = policy.route(ip, prefix)
            override fun excludeRoute(ip: String, prefix: Int) = policy.exclude(ip, prefix)
            override fun addAddress(ip: String, prefix: Int) {
                require((TailscaleRoutePolicy.isOverlayV4(ip) && prefix == 32) ||
                    (TailscaleRoutePolicy.isOverlayV6(ip) && prefix == 128))
                builder.addAddress(ip, prefix)
            }
            override fun establish(): com.novacinema.engines.libtailscale.ParcelFileDescriptor {
                policy.ready(); builder.addRoute(address, 32)
                val descriptor = checkNotNull(builder.establish())
                return object : com.novacinema.engines.libtailscale.ParcelFileDescriptor {
                    override fun detach(): Int = descriptor.detachFd()
                }
            }
        }
    }
}
