package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.novacinema.connect.core.*
import java.util.concurrent.Executors

/** TV/phone laboratory association. No credentials, routes or VPN keys are entered here. */
class DevicePairingActivity : Activity() {
    private val io = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var manager: DevicePairing
    private lateinit var status: TextView
    private lateinit var code: TextView
    private lateinit var review: TextView
    private lateinit var confirm: Button
    private lateinit var importButton: Button
    private lateinit var refresh: Button
    private lateinit var forget: Button
    private var invitation: DeviceInvitation? = null
    private var foreground = false
    private var generation = 0
    private val poll = Runnable { work { manager.poll() } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        manager = DeviceAssociationRuntime.get(this)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(44, 36, 44, 36) }
        fun text(value: String, size: Float = 20f) = TextView(this).apply { text = value; textSize = size; root.addView(this) }
        fun button(label: String, action: () -> Unit) = Button(this).apply {
            text = label; isFocusable = true; setOnClickListener { action() }; root.addView(this)
        }
        text("Associar ao NOVA Server · Laboratório", 28f)
        text("Importa o ficheiro de ligação fornecido pelo proprietário. A biblioteca e a reprodução chegam numa próxima fase.")
        status = text("A verificar associação…")
        code = text("", 36f).apply { contentDescription = "Código de associação" }
        importButton = button("Importar ligação do proprietário") {
            handler.removeCallbacks(poll)
            try {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type = "*/*"
                }, 702)
            } catch (_: android.content.ActivityNotFoundException) {
                status.text = "Este aparelho não disponibiliza seleção de ficheiros. O ensaio requer um fornecedor de documentos; a descoberta automática ainda não está disponível."
            }
        }
        review = text("")
        confirm = button("Confirmei a impressão digital com o proprietário") {
            val selected = invitation ?: return@button
            invitation = null; review.text = ""; confirm.visibility = android.view.View.GONE
            work {
                val trust = selected.confirm(selected.fingerprint)
                manager.begin(trust, "Android TV NOVA")
            }
        }.apply { visibility = android.view.View.GONE }
        refresh = button("Verificar associação") { work { manager.check() } }
        forget = button("Esquecer associação nesta TV") {
            invitation = null; review.text = ""; confirm.visibility = android.view.View.GONE
            work { manager.forget(); PairingView(PairingState.EMPTY) }
        }
        button("Voltar") { finish() }
        setContentView(ScrollView(this).apply { addView(root) })
        importButton.requestFocus()
    }

    override fun onStart() { super.onStart(); foreground = true; work { manager.resume() } }
    override fun onStop() {
        foreground = false; generation++; handler.removeCallbacks(poll)
        super.onStop()
    }
    override fun onDestroy() { io.shutdownNow(); super.onDestroy() }

    @Deprecated("Platform result API keeps the diagnostic client dependency-light")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 702 || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        // Only the chosen document is read. No storage permission or persistent URI grant.
        io.execute {
            try {
                val raw = contentResolver.openInputStream(uri)?.use { it.bounded(16_384) } ?: throw DeviceProtocolFailure()
                runOnUiThread {
                    if (!isDestroyed) try { reviewInvitation(raw) }
                    catch (_: Exception) { status.text = "Ficheiro inválido ou expirado. Pede uma ligação nova ao proprietário." }
                }
            } catch (_: Exception) {
                runOnUiThread { if (!isDestroyed) status.text = "Ficheiro inacessível. Pede uma ligação nova ao proprietário." }
            }
        }
    }

    internal fun reviewInvitation(raw: ByteArray) {
        val parsed = DeviceInvitation.parse(raw)
        generation++; handler.removeCallbacks(poll)
        invitation = parsed
        code.text = ""
        importButton.isEnabled = true; forget.isEnabled = true; refresh.isEnabled = false
        review.text = "Servidor: ${parsed.trust.serverId}\nLigação: ${parsed.trust.origin}\n" +
            "Impressão digital do ficheiro:\n${parsed.fingerprint.chunked(8).joinToString(" ")}\n" +
            "Compara todos os caracteres com o valor fornecido pelo proprietário por um canal de confiança. Não confirmes se forem diferentes."
        confirm.visibility = android.view.View.VISIBLE
        confirm.isEnabled = true
        status.text = "Aguardando confirmação da identidade. Ainda não foi feita uma ligação ao servidor."
        confirm.requestFocus()
    }

    private fun work(operation: () -> PairingView) {
        handler.removeCallbacks(poll)
        val current = ++generation
        listOf(importButton, refresh, forget, confirm).forEach { it.isEnabled = false }
        io.execute {
            val value = try { operation() }
            catch (_: javax.net.ssl.SSLException) { PairingView(PairingState.SECURITY_ERROR) }
            catch (_: DeviceProtocolFailure) { PairingView(PairingState.SECURITY_ERROR) }
            catch (_: Exception) { PairingView(PairingState.REASSOCIATE) }
            runOnUiThread {
                if (!foreground || current != generation || isDestroyed) return@runOnUiThread
                listOf(importButton, refresh, forget, confirm).forEach { it.isEnabled = true }
                render(value)
            }
        }
    }

    private fun render(value: PairingView) {
        code.text = value.userCode.orEmpty()
        status.text = when (value.state) {
            PairingState.EMPTY -> "Sem associação. Se esqueceste a TV enquanto estava offline, o proprietário pode revogá-la no Control."
            PairingState.WAITING -> "No NOVA Control, introduz este código e confirma este dispositivo. Aguarda a aprovação."
            PairingState.ASSOCIATED -> "Dispositivo associado e identidade confirmada. Biblioteca, filmes e ligação VPN ainda não estão disponíveis neste percurso."
            PairingState.OFFLINE -> "Servidor indisponível. A associação foi preservada; volta a verificar quando houver ligação."
            PairingState.EXPIRED -> "Código expirado. Importa a ligação para pedir um novo código."
            PairingState.DENIED -> "O proprietário recusou este pedido."
            PairingState.REASSOCIATE -> "É necessário associar novamente. Verifica a ligação e importa um ficheiro válido do proprietário."
            PairingState.SECURITY_ERROR -> "Identidade ou certificado não corresponde ao aprovado. Ligação bloqueada; contacta o proprietário."
        }
        importButton.isEnabled = value.state !in setOf(PairingState.WAITING, PairingState.ASSOCIATED, PairingState.OFFLINE)
        refresh.isEnabled = value.state != PairingState.WAITING
        if (value.state == PairingState.WAITING && foreground)
            handler.postDelayed(poll, maxOf(250L, value.nextPollMillis - System.currentTimeMillis()))
    }
}
