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
    private val images = Executors.newFixedThreadPool(2) as java.util.concurrent.ThreadPoolExecutor
    private lateinit var home:CinemaHomeView
    private lateinit var status: TextView
    private lateinit var primary: Button
    @Volatile private var generation = 0
    private var lastFocus:String?=null
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        home=CinemaHomeView(this,{ open(DirectoryActivity::class.java) },{ open(ConnectionActivity::class.java) },
            { open(DevicePairingActivity::class.java) },{ open(DirectorySetupActivity::class.java) })
        status=home.status;primary=home.primary
        primary.requestFocus()
    }
    private fun open(target: Class<out Activity>) { startActivity(Intent(this, target)) }
    override fun onStart() {
        super.onStart()
        home.resetPreview()
        val current = ++generation
        io.execute {
            val saved = runCatching { DeviceSessionStore(applicationContext).loadBase() }
            val configured = runCatching { DirectoryProfile.load(applicationContext) }.isSuccess
            val network=TvUi.network(applicationContext)
            runOnUiThread {
                if (isDestroyed || current != generation) return@runOnUiThread
                val associated = saved.getOrNull() != null
                status.text = when {
                    saved.isFailure -> "Não foi possível ler a associação. Abre Conta e associação para recuperar."
                    associated -> "$network · A verificar a tua biblioteca…"
                    configured -> "Configuração pronta. Entra com a conta que o proprietário partilhou contigo."
                    else -> "Primeira utilização: configura esta TV com os dados fornecidos pelo proprietário."
                }
                primary.text = when { associated -> "Abrir biblioteca"; configured -> "Entrar na NOVA"; else -> "Entrar na NOVA · configurar TV" }
                primary.setOnClickListener { open(when {
                    associated -> CinemaActivity::class.java
                    configured -> DirectoryActivity::class.java
                    else -> DirectorySetupActivity::class.java
                }) }
                if(associated)loadPreview(current)
            }
        }
    }
    private fun loadPreview(current:Int) {
        io.execute {
            val result=runCatching {
                val client=MediaClient(this);val saved=client.session()
                val library=DeviceClient(saved.trust).permissions(saved).firstOrNull()
                Triple(library,library?.let { client.page(it.first).items }.orEmpty(),saved)
            }
            runOnUiThread {
                if(isDestroyed || generation!=current)return@runOnUiThread
                result.fold({ (library,items,saved) ->
                    status.text="Conta e servidor verificados · ${TvUi.network(this)}"
                    home.preview(library?.first.orEmpty(),items,{ item ->
                        startActivity(Intent(this,CinemaActivity::class.java).putExtra("library",library?.first)
                            .putExtra("libraryName",library?.second).putExtra("selected",item.id))
                    },{ card ->
                        images.execute {
                            if(generation!=current)return@execute
                            val bitmap=runCatching { MediaClient(this).image(library!!.first,card.item.id,saved) }.getOrNull()
                            if(bitmap!=null)runOnUiThread {
                                if(!isDestroyed && generation==current) {
                                    card.artwork.bitmap=bitmap;card.invalidate()
                                    home.artworkLoaded(card)
                                }
                            }
                        }
                    })
                    home.restoreFocus(lastFocus)
                },{ status.text="Não foi possível verificar a biblioteca. Consulta a ligação ou tenta abri-la novamente.";home.unavailable() })
            }
        }
    }
    override fun onStop() { lastFocus=home.focusedItem();generation++;images.queue.clear();home.resetPreview();super.onStop() }
    override fun onDestroy() { io.shutdown();images.shutdownNow();super.onDestroy() }
}
