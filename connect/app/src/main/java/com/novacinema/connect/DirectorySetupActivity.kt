package com.novacinema.connect

import android.app.Activity
import android.os.Bundle
import android.view.WindowManager
import android.widget.*
import java.util.concurrent.Executors

class DirectorySetupActivity:Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private var foreground=false
    private var generation=0
    override fun onCreate(state:Bundle?) {
        super.onCreate(state);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(44,32,44,32) }
        fun label(value:String)=TextView(this).apply { text=value;textSize=21f;root.addView(this) }
        label("Configurar NOVA nesta TV")
        label("O proprietário encontra estes dois valores no NOVA Control ou no pacote de instalação. Compara a impressão digital completa antes de confirmar.")
        val origin=EditText(this).apply { hint="Directory · https://192.168.x.x:9443";tag="setup-origin";setSingleLine();root.addView(this) }
        val pin=EditText(this).apply { hint="Impressão digital TLS · 64 caracteres";tag="setup-fingerprint";setSingleLine();root.addView(this) }
        val message=label("A configuração só é guardada depois de validar a identidade e o certificado.")
        val confirm=Button(this).apply { text="Confirmar identidade e configurar";tag="setup-confirm";root.addView(this) }
        confirm.setOnClickListener {
            val url=origin.text.toString().trim();val fingerprint=pin.text.toString().trim().lowercase()
            val approved=runCatching { DirectoryProfile.load(this) }.getOrNull()
            if(approved!=null && (approved.origin!=url || com.novacinema.connect.core.ServerTrust.fingerprint(approved.certificateDer)!=fingerprint)) {
                message.text="Esta instalação já tem uma identidade aprovada. Contacta o proprietário; a configuração não foi substituída."
                return@setOnClickListener
            }
            val current=++generation;confirm.isEnabled=false;message.text="A validar o servidor…"
            io.execute {
                val result=runCatching { DirectoryBootstrap.fetch(url,fingerprint) }
                runOnUiThread {
                    if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                    confirm.isEnabled=true
                    result.fold({ raw ->
                        try { DirectorySetupStore(this).saveNew(raw);message.text="Configuração guardada. Já podes entrar na NOVA.";confirm.isEnabled=false }
                        catch(_:Exception) { message.text="A configuração existente difere ou está danificada. Contacta o proprietário; a identidade não foi substituída." }
                    },{ message.text="Identidade não confirmada. Verifica o endereço, os 64 caracteres, o relógio e a ligação à rede. Nenhuma configuração foi alterada." })
                }
            }
        }
        root.addView(Button(this).apply { text="Voltar à entrada";setOnClickListener { finish() } })
        setContentView(ScrollView(this).apply { addView(root) });origin.requestFocus()
    }
    override fun onStart() { super.onStart();foreground=true }
    override fun onStop() { foreground=false;generation++;super.onStop() }
    override fun onDestroy() { io.shutdownNow();super.onDestroy() }
}
