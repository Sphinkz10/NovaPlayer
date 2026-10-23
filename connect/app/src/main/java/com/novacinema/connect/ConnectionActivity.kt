package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.view.WindowManager
import android.widget.*
import com.novacinema.connect.core.*
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/** Functional TV entrypoint. Remote identity verification precedes Cinema. */
class ConnectionActivity : Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private val busy=AtomicBoolean(false)
    private lateinit var status:TextView
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root=TvUi.screen(this,"Ligação ao servidor","Escolhe como esta TV chega ao teu NOVA Server.")
        status=TvUi.label(root, "").apply { text=if(RemoteWireGuardRuntime.selected(this@ConnectionActivity))
            "WireGuard selecionado. Liga e verifica o servidor para abrir o Cinema." else "Ligação local selecionada." }
        fun button(label:String,action:()->Unit)=TvUi.button(root,label,action=action)
        val cinema=button("Abrir biblioteca") { startActivity(Intent(this,CinemaActivity::class.java)) }
        button("Preparar WireGuard nesta TV") { work {
            when(RemoteWireGuardRuntime.prepare(applicationContext)) {
                "pending" -> {
                    val saved=DeviceSessionStore(applicationContext).loadBase() ?: error("Association unavailable")
                    "Pedido enviado. Compara esta impressão digital no Control e aprova a TV. Depois volta a preparar:\n"+
                        WireGuardEnrollmentStore(applicationContext).fingerprint(saved)
                }
                "approved" -> "Configuração recebida pela ligação segura e guardada nesta TV. Podes ligar o WireGuard."
                else -> "WireGuard revogado. O proprietário deve rever esta associação."
            }
        } }
        button("Ligar WireGuard") {
            val consent=VpnService.prepare(this)
            if(consent!=null)startActivityForResult(consent,401) else connect()
        }
        button("Renovar WireGuard pela ligação atual") { work {
            check(RemoteWireGuardRuntime.renew(applicationContext))
            "Perfil renovado pelo túnel seguro. Podes continuar a usar o Cinema."
        } }
        button("Desligar WireGuard e usar LAN") { work {
            RemoteWireGuardRuntime.disconnectToLan(applicationContext);"Túnel desligado. Ligação local selecionada."
        } }
        TvUi.label(root,"Prepara o WireGuard na rede local, depois da associação e aprovação no Control. O perfil dura 24 horas e renova-se pelo túnel enquanto ligado. Se expirar sem ligação, prepara-o novamente na LAN.\nTailscale e NetBird: integração nativa ainda indisponível nesta versão.",16f,TvUi.muted)
        button("Voltar") { finish() };cinema.requestFocus()
    }
    private fun note(value:String) { runOnUiThread { if(!isDestroyed)status.text=value } }
    private fun work(action:()->String) {
        if(!busy.compareAndSet(false,true))return
        note("A verificar…")
        io.execute {
            try { note(action()) }
            catch (_:Exception) { note("Ligação não confirmada. Verifica a associação, a aprovação no Control e a configuração do gateway. A seleção de rede foi mantida.") }
            finally { busy.set(false) }
        }
    }
    private fun connect() = work {
        if(RemoteWireGuardRuntime.connect(applicationContext)) "Servidor NOVA verificado pelo WireGuard. Podes abrir o Cinema."
        else "Servidor não confirmado pelo túnel. Verifica a rede e o gateway."
    }
    @Deprecated("Platform consent result for API 26 compatibility")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==401) { if(resultCode==RESULT_OK)connect() else note("VPN não autorizada pelo Android.") }
    }
    override fun onDestroy() { io.shutdown();super.onDestroy() }
}
