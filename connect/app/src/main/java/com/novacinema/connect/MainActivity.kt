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
class MainActivity : Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private val busy=AtomicBoolean(false)
    private lateinit var status:TextView
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(46,36,46,36) }
        root.addView(TextView(this).apply { text="NOVA Cinema · "+packageManager.getPackageInfo(packageName,0).versionName;textSize=28f })
        status=TextView(this).apply { textSize=20f;text=if(RemoteWireGuardRuntime.selected(this@MainActivity))
            "WireGuard selecionado. Liga e verifica o servidor para abrir o Cinema." else "Ligação local selecionada." }
        root.addView(status)
        fun button(label:String,action:()->Unit)=Button(this).apply { text=label;setOnClickListener { action() };root.addView(this) }
        val directory=button("Entrar na NOVA · Directory") { startActivity(Intent(this,DirectoryActivity::class.java)) }
        button("Associar ao NOVA Server") { startActivity(Intent(this,DevicePairingActivity::class.java)) }
        button("Abrir NOVA Cinema") { startActivity(Intent(this,CinemaActivity::class.java)) }
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
        button("Desligar WireGuard e usar LAN") { work {
            RemoteWireGuardRuntime.disconnectToLan(applicationContext);"Túnel desligado. Ligação local selecionada."
        } }
        root.addView(TextView(this).apply { textSize=17f;text="Prepara o WireGuard na rede local, depois da associação e aprovação no Control. A configuração expira em 24 horas.\nTailscale e NetBird: integração nativa ainda indisponível nesta versão." })
        setContentView(ScrollView(this).apply { addView(root) });directory.requestFocus()
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
