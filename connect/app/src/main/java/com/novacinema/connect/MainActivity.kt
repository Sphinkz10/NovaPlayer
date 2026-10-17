package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.ScrollView
import com.novacinema.connect.core.JellyfinStatus
import com.novacinema.connect.core.ProviderId
import com.novacinema.connect.core.ProviderRegistry
import com.novacinema.connect.core.ProviderObservation
import com.novacinema.connect.core.ProviderState
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Diagnostic TV harness only; not the premium NOVA Cinema frontend. */
class MainActivity : Activity() {
    private val io = Executors.newSingleThreadExecutor()
    private val connecting = AtomicBoolean(false)
    private lateinit var status: TextView
    private lateinit var bridge: WireGuardBridge
    private lateinit var provisioning: ProvisioningStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        provisioning = ProvisioningStore(this)
        bridge = WireGuardBridge(this)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(46, 46, 46, 46) }
        val label = TextView(this).apply { text = "NOVA Connect · Laboratório 0.4"; textSize = 26f }
        status = TextView(this).apply { textSize = 21f; text = "Sem credenciais no APK. Associação administrativa ainda por implementar." }
        val device = AndroidCapabilities.read(this)
        val compatibility = TextView(this).apply {
            textSize = 18f
            text = "Android API ${device.sdk} · ${device.abis.joinToString()} · TV: ${device.television}\n" +
                ProviderId.entries.joinToString("\n") { provider ->
                    val result = ProviderRegistry.evaluate(provider, device, ProviderObservation())
                    val description = when (result) {
                        ProviderState.NEEDS_PROVISIONING -> "motor incluído; associação e rede por validar"
                        ProviderState.NOT_IMPLEMENTED -> "motor nativo ainda por integrar"
                        else -> "dispositivo sem suporte nesta compilação"
                    }
                    "${provider.wireId}: $description"
                }
        }
        val connect = Button(this).apply { text = "Validar WireGuard privado"; setOnClickListener { begin() } }
        val disconnect = Button(this).apply { text = "Desligar túnel"; setOnClickListener { stopTunnel() } }
        root.addView(label); root.addView(compatibility); root.addView(status); root.addView(connect); root.addView(disconnect)
        setContentView(ScrollView(this).apply { addView(root) })
        connect.requestFocus()
    }

    override fun onStart() {
        super.onStart()
        // Best-effort reconnect when the app is opened again and Android consent is already valid.
        // This does NOT implement unattended recovery after a device restart.
        if (provisioning.load() != null && VpnService.prepare(this) == null &&
            runCatching { !bridge.isTunnelUp() }.getOrDefault(false)) connectInBackground()
    }

    private fun note(text: String) { runOnUiThread { status.text = text } }

    private fun begin() {
        if (ProviderRegistry.evaluate(ProviderId.WIREGUARD, AndroidCapabilities.read(this), ProviderObservation()) == ProviderState.UNSUPPORTED_DEVICE) {
            note("Este Android/ABI não é suportado pelo motor incluído.")
            return
        }
        if (provisioning.load() == null) {
            note("Dispositivo não associado. O administrador deverá aprovar este equipamento numa versão futura.")
            return
        }
        val consent = VpnService.prepare(this)
        if (consent != null) { note("A aguardar autorização de VPN do Android."); startActivityForResult(consent, 401); return }
        connectInBackground()
    }

    @Deprecated("Activity result API used only to keep this diagnostic POC dependency-light")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 401) {
            if (resultCode == RESULT_OK) connectInBackground() else note("VPN não autorizada. Nenhuma ligação remota foi iniciada.")
        }
    }

    private fun connectInBackground() {
        if (!connecting.compareAndSet(false, true)) return
        io.execute {
            try {
                val p = provisioning.load() ?: return@execute note("Configuração privada indisponível.")
                if (VpnService.prepare(this) != null) return@execute note("Autorização VPN foi revogada.")
                if (!bridge.connect(p.config, p.jellyfinUrl)) return@execute note("Túnel não estabelecido.")
                val result = JellyfinHttpProbe().check(p.jellyfinUrl, p.expectedServerId)
                note(when (result.status) {
                    JellyfinStatus.READY -> "VPN ligada. Jellyfin responde. Falta autenticação do utilizador."
                    JellyfinStatus.SETUP_REQUIRED -> "VPN ligada. O Jellyfin exige configuração inicial pelo administrador."
                    JellyfinStatus.TEMPORARILY_UNAVAILABLE -> "VPN ligada. Jellyfin indisponível temporariamente. Mantém dados locais."
                    JellyfinStatus.OFFLINE -> "VPN ligada, mas não foi possível contactar o Jellyfin."
                    JellyfinStatus.TLS_VALIDATION_FAILED -> "Certificado HTTPS não validado. Contacta o administrador; não há bypass."
                    JellyfinStatus.SECURITY_BLOCKED -> "Ligação bloqueada pela política de segurança. Contacta o administrador."
                    JellyfinStatus.SERVER_IDENTITY_MISMATCH -> "Identidade do servidor não corresponde à aprovada. Ligação rejeitada."
                    else -> "VPN ligada. Estado Jellyfin: ${result.status}."
                })
            } catch (_: Exception) {
                note("Não foi possível estabelecer ligação privada. Sem fallback público.")
            } finally {
                connecting.set(false)
            }
        }
    }

    private fun stopTunnel() { io.execute { try { bridge.disconnect(); note("Túnel desligado.") } catch (_: Exception) { note("Não foi possível desligar o túnel.") } } }
    override fun onDestroy() { io.shutdownNow(); super.onDestroy() }
}
