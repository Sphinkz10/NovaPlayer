package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.*
import android.net.VpnService
import android.os.*
import com.wireguard.android.backend.GoBackend
import org.json.JSONObject
import java.io.File
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Actual Android VPN -> Tailscale peer -> NOVA HTTPS; no external Tailscale Android app. */
class TailscaleNetworkInstrumentation : Instrumentation() {
    private var mode = ""
    private val checks = mutableListOf<String>()
    private var service: Messenger? = null
    private val replies = HandlerThread("tailscale-proof-replies")
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); mode = arguments?.getString("mode").orEmpty(); start() }
    private fun request(command: Int, options: Bundle = Bundle()): Bundle {
        val done = CountDownLatch(1); val result = AtomicReference<Bundle>()
        val callback = Messenger(Handler(replies.looper) { message ->
            result.set(Bundle(message.data)); done.countDown(); true
        })
        checkNotNull(service).send(Message.obtain(null, command).apply { data = options; replyTo = callback })
        check(done.await(50, TimeUnit.SECONDS)) { "Private VPN service did not reply" }
        return checkNotNull(result.get())
    }
    private fun stage(name: String) = sendStatus(1, Bundle().apply { putString("tailscale_stage", name) })
    private fun waitFor(timeout: Long = 60000, action: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + timeout
        while (!action()) { check(SystemClock.elapsedRealtime() < deadline) { "Network proof deadline exceeded" }; Thread.sleep(300) }
    }
    private fun blocked(host: String, port: Int): Boolean = runCatching {
        Socket().use { it.connect(InetSocketAddress(host, port), 1500) }
    }.isFailure
    override fun onStart() {
        val report = Bundle(); var bound = false
        var connected = CountDownLatch(1)
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) { service = Messenger(binder); connected.countDown() }
            override fun onServiceDisconnected(name: ComponentName) { service = null }
        }
        try {
            check(mode in setOf("network", "restart", "tamper", "missing-key"))
            val fixture = JSONObject(File(targetContext.filesDir, "tailscale-fixture.json").readText())
            val gateway = fixture.getString("gateway")
            check(TailscaleRoutePolicy.isOverlayV4(gateway))
            for (invalid in listOf("100.63.255.255", "100.128.0.1", "10.0.0.1", "100.064.0.1", "example.com"))
                check(!TailscaleRoutePolicy.isOverlayV4(invalid))
            check(runCatching { TailscaleRoutePolicy(gateway).route("0.0.0.0", 0) }.isFailure)
            check(runCatching { TailscaleRoutePolicy(gateway).route("192.168.0.0", 16) }.isFailure)
            check(runCatching { TailscaleRoutePolicy(gateway).ready() }.isFailure)
            val narrowed = TailscaleRoutePolicy(gateway).apply { route("100.64.0.0", 10) }; narrowed.ready()
            narrowed.exclude(gateway, 32); check(runCatching { narrowed.ready() }.isFailure)
            checks.add("CGNAT validation and route narrowing reject defaults, LAN and excluded gateway")
            check(blocked(gateway, 9444)); checks.add("NOVA gateway unreachable before VPN")
            check(GoBackend(targetContext).version.isNotBlank())
            checks.add("WireGuard native runtime remains usable in the main process")
            // Match a user-initiated connection from the visible TV app on every run,
            // including when Android has already remembered VPN consent.
            val activity = startActivitySync(Intent(targetContext, TailscaleConsentActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as TailscaleConsentActivity
            if (VpnService.prepare(targetContext) != null) {
                runOnMainSync { (activity.findViewById<android.view.View>(android.R.id.content) as android.view.ViewGroup)
                    .getChildAt(0).performClick() }
                stage("consent")
                waitFor { TailscaleConsentActivity.approved }
            }
            val intent = Intent(targetContext, TailscaleVpnService::class.java)
            if (mode == "missing-key") {
                java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                    .deleteEntry("nova-tailscale-state-v1")
            }
            targetContext.startForegroundService(intent)
            replies.start(); bound = targetContext.bindService(intent, connection, Context.BIND_AUTO_CREATE)
            check(bound && connected.await(15, TimeUnit.SECONDS))
            val options = Bundle().apply {
                putString("control", fixture.getString("control")); putString("gateway", gateway)
                putByteArray("fixture_ca", fixture.getString("control_ca").toByteArray())
                putString("auth_key", fixture.optString("auth_key"))
            }
            val initial = request(1, options)
            if (mode == "tamper" || mode == "missing-key") {
                check(initial.getString("result") == "refused")
                check(initial.getString("failure_stage") == "state-preflight")
                check(blocked(gateway, 9444))
                if (mode == "missing-key") {
                    check(!java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                        .containsAlias("nova-tailscale-state-v1"))
                    checks.add("missing wrapping key refused before engine initialization without regenerating it")
                } else checks.add("tampered persisted state refused before engine initialization; no replacement identity")
            } else {
                check(initial.getString("result") == "ok") {
                    "Native initialization refused: ${initial.getString("failure_stage")}/${initial.getString("failure_type")}/${initial.getInt("api_status")}" }
                check(initial.getInt("pid") > 0 && initial.getInt("pid") != Process.myPid())
                checks.add("Tailscale JNI and WireGuard JNI execute in separate processes")
                var status = Bundle()
                waitFor(90000) { status = request(2); status.getBoolean("tun") && status.getString("backend") == "Running" }
                checks.add("native Tailscale backend running with real Android TUN")
                val node = checkNotNull(status.getString("node_key")); check(node.startsWith("nodekey:"))
                if (mode == "restart") check(node == fixture.getString("expected_node_key"))
                report.putString("node_key", node)
                val cert = fixture.getString("certificate_pem").toByteArray()
                fun identity() = TailscaleHttps.identity(gateway, 9444, cert, fixture.getString("access_token"))
                var identity: JSONObject? = null
                waitFor { identity = runCatching { identity() }.getOrNull(); identity != null }
                check(identity!!.getString("server_id") == fixture.getString("server_id"))
                check(identity!!.getString("device_id") == fixture.getString("device_id"))
                checks.add("authenticated NOVA identity over pinned HTTPS through the native Tailscale tunnel")
                check(runCatching { TailscaleHttps.identity(gateway, 9444,
                    fixture.getString("wrong_certificate_pem").toByteArray(), fixture.getString("access_token")) }.isFailure)
                checks.add("incorrect gateway certificate refused")
                check(blocked(gateway, 22) && blocked(gateway, 9443))
                checks.add("live SSH and administration canaries inaccessible through the overlay")
                if (mode == "restart") {
                    checks.add("same Tailscale node identity reconnects after force-stop without enrollment auth key")
                    stage("revoke")
                    waitFor(90000) { File(targetContext.filesDir, "tailscale-gate.txt").let { it.exists() && it.readText() == "revoked" } }
                    waitFor(60000) { blocked(gateway, 9444) }
                    waitFor(60000) { runCatching { identity() }.isFailure }
                    // Repeated failures after coordinator expiry, not just a transient first failure.
                    repeat(3) { check(runCatching { identity() }.isFailure); Thread.sleep(500) }
                    checks.add("coordinator node expiry removes private NOVA access")
                }
                check(request(3).getString("result") == "ok")
                check(blocked(gateway, 9444)); checks.add("explicit disconnect closes private access")
                if (mode == "network") {
                    targetContext.unbindService(connection); bound = false; service = null
                    targetContext.stopService(intent)
                    runOnMainSync { }; Thread.sleep(500)
                    connected = CountDownLatch(1)
                    targetContext.startForegroundService(intent)
                    bound = targetContext.bindService(intent, connection, Context.BIND_AUTO_CREATE)
                    check(bound && connected.await(15, TimeUnit.SECONDS))
                    options.remove("auth_key")
                    val reconnect = request(1, options)
                    check(reconnect.getString("result") == "ok" && reconnect.getInt("pid") == initial.getInt("pid"))
                    waitFor { val next = request(2); next.getBoolean("tun") && next.getString("node_key") == node &&
                        runCatching { identity() }.isSuccess }
                    checks.add("service recreation reuses one Go Application and the same node within its original process")
                    check(request(3).getString("result") == "ok" && blocked(gateway, 9444))
                }
            }
            report.putString("nova_tailscale", "passed"); report.putString("mode", mode)
            report.putInt("api", Build.VERSION.SDK_INT); report.putStringArrayList("checks", ArrayList(checks))
            report.putInt("checks_count", checks.size)
            finish(Activity.RESULT_OK, report)
        } catch (failure: Throwable) {
            report.putString("nova_tailscale", "failed")
            report.putString("failure", failure.stackTraceToString())
            finish(Activity.RESULT_CANCELED, report)
        } finally {
            if (bound) targetContext.unbindService(connection)
            targetContext.stopService(Intent(targetContext, TailscaleVpnService::class.java))
            replies.quitSafely()
        }
    }
}
