package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import java.util.concurrent.Executors

/** TV home: configuration, account and connection details live outside the catalogue. */
class MainActivity : Activity() {
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var primary: Button
    private var generation = 0
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root = TvUi.screen(this, "O teu cinema. Em casa ou contigo.", "Os teus filmes e séries, nas bibliotecas partilhadas contigo.")
        status = TvUi.label(root, "A ler a configuração desta TV…", 18f, TvUi.accent)
        primary = TvUi.button(root, "Entrar na NOVA", "home-primary") { open(DirectoryActivity::class.java) }
        val row = TvUi.row(root)
        TvUi.button(row, "Ligação", "home-connection") { open(ConnectionActivity::class.java) }
        TvUi.button(row, "Conta e associação", "home-account") { open(DevicePairingActivity::class.java) }
        TvUi.button(row, "Configurar TV", "home-setup") { open(DirectorySetupActivity::class.java) }
        TvUi.label(root, "Usa as setas e OK para escolher. Voltar regressa ao ecrã anterior.", 15f, TvUi.muted)
        TvUi.label(root, "NOVA Cinema · " + packageManager.getPackageInfo(packageName, 0).versionName, 13f, TvUi.muted)
        primary.requestFocus()
    }
    private fun open(target: Class<out Activity>) { startActivity(Intent(this, target)) }
    override fun onStart() {
        super.onStart()
        val current = ++generation
        io.execute {
            val saved = runCatching { DeviceSessionStore(applicationContext).loadBase() }
            val configured = runCatching { DirectoryProfile.load(applicationContext) }.isSuccess
            val remote = RemoteWireGuardRuntime.selected(applicationContext)
            runOnUiThread {
                if (isDestroyed || current != generation) return@runOnUiThread
                val associated = saved.getOrNull() != null
                status.text = when {
                    saved.isFailure -> "Não foi possível ler a associação. Abre Conta e associação para recuperar."
                    associated && remote -> "WireGuard selecionado. A identidade do servidor será verificada antes de abrir a biblioteca."
                    associated -> "TV associada · Rede local. Escolhe a tua biblioteca para começar."
                    configured -> "Configuração pronta. Entra com a conta que o proprietário partilhou contigo."
                    else -> "Primeira utilização: configura esta TV com os dados fornecidos pelo proprietário."
                }
                primary.text = when { associated -> "Abrir biblioteca"; configured -> "Entrar na NOVA"; else -> "Entrar na NOVA · configurar TV" }
                primary.setOnClickListener { open(when {
                    associated -> CinemaActivity::class.java
                    configured -> DirectoryActivity::class.java
                    else -> DirectorySetupActivity::class.java
                }) }
            }
        }
    }
    override fun onStop() { generation++; super.onStop() }
    override fun onDestroy() { io.shutdown(); super.onDestroy() }
}
