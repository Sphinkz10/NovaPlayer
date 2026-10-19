package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.*
import java.util.concurrent.Executors

/** Deployment bootstrap is configured by the owner; family members only enter their own account. */
class DirectoryActivity:Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private lateinit var username:EditText
    private lateinit var password:EditText
    private lateinit var message:TextView
    private lateinit var login:Button
    private lateinit var servers:LinearLayout
    private var profile:DirectoryProfile?=null
    private var client:DirectoryClient?=null
    private var foreground=false
    private var generation=0

    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(44,36,44,36) }
        fun text(value:String,size:Float=20f)=TextView(this).apply { text=value;textSize=size;root.addView(this) }
        text("Entrar na NOVA",28f)
        text("Usa a tua conta Directory. Depois escolhe um servidor partilhado contigo e confirma a TV com o proprietário.")
        username=EditText(this).apply {
            hint="Conta Directory";tag="directory-username";maxLines=1;isSingleLine=true
            inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO;imeOptions=EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        };root.addView(username)
        password=EditText(this).apply {
            hint="Palavra-passe Directory";tag="directory-password";maxLines=1;isSingleLine=true
            inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO;imeOptions=EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        };root.addView(password)
        login=Button(this).apply { text="Entrar e encontrar servidores";setOnClickListener { discover() } };root.addView(login)
        message=text("A verificar configuração do Directory…")
        servers=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL };root.addView(servers)
        root.addView(Button(this).apply { text="Voltar";setOnClickListener { finish() } })
        setContentView(ScrollView(this).apply { addView(root) })
        profile=runCatching { DirectoryProfile.load(this) }.getOrNull()
        login.isEnabled=profile!=null
        message.text=if(profile==null)"O proprietário precisa de configurar o Directory nesta instalação da app. Não introduzas endereços ou credenciais administrativas na TV."
            else "Directory configurado. A palavra-passe é usada apenas nesta sessão."
        username.requestFocus()
    }
    override fun onStart() { super.onStart();foreground=true;login.isEnabled=profile!=null }
    override fun onStop() {
        foreground=false;generation++;password.text.clear();servers.removeAllViews()
        val previous=client;client=null;if(previous!=null)io.execute { previous.close() }
        super.onStop()
    }
    override fun onDestroy() { io.shutdown();super.onDestroy() }

    private fun discover() {
        val selected=profile ?: return
        val name=username.text.toString().trim();val secret=password.text.toString();password.text.clear()
        if(!name.matches(Regex("[a-z][a-z0-9_.-]{2,39}")) || secret.length !in 1..1024) {
            message.text="Verifica a conta e a palavra-passe.";return
        }
        val current=++generation;val previous=client
        val connection=runCatching { DirectoryClient(selected) }.getOrElse {
            message.text="Configuração TLS indisponível ou expirada. Contacta o proprietário.";return
        };client=connection
        login.isEnabled=false;servers.removeAllViews();message.text="A procurar os teus servidores…"
        io.execute {
            try {
                previous?.close();connection.login(name,secret);val entries=connection.discover()
                runOnUiThread {
                    if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                    message.text=if(entries.isEmpty())"Não tens servidores autorizados neste momento. Pede ao proprietário que partilhe o servidor contigo."
                        else "Escolhe o servidor para esta conta. Trocar de conta/servidor exige uma nova associação."
                    entries.forEach { entry -> servers.addView(Button(this).apply {
                        text="Associar a "+entry.name;tag="directory-entry-"+entry.id
                        setOnClickListener { select(connection,selected,entry) }
                    }) }
                    login.isEnabled=true
                }
            } catch(error:Exception) {
                connection.close()
                runOnUiThread {
                    if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                    message.text=if(error is DirectoryFailure && error.status in listOf(401,403))"Conta ou palavra-passe recusada."
                        else "Não foi possível validar o Directory. Verifica a ligação ou contacta o proprietário."
                    login.isEnabled=true
                }
            }
        }
    }
    private fun select(connection:DirectoryClient,selected:DirectoryProfile,entry:DirectoryEntry) {
        val current=++generation;login.isEnabled=false
        for(i in 0 until servers.childCount)servers.getChildAt(i).isEnabled=false
        message.text="A confirmar a conta e a identidade do servidor…"
        io.execute {
            try {
                val account=connection.account ?: error("Session ended")
                val assertion=connection.assertion(entry)
                DirectoryPins(this).accept(selected,entry)
                runOnUiThread {
                    if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                    DirectorySelectionRuntime.put(DirectorySelection(entry,account,assertion))
                    startActivity(Intent(this,DevicePairingActivity::class.java).putExtra("directory_selection",true))
                }
            } catch(_:Exception) {
                runOnUiThread {
                    if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                    message.text="Servidor expirado, sem autorização ou com identidade alterada. Volta a entrar; uma chave alterada exige revisão pelo proprietário."
                    login.isEnabled=true
                }
            }
        }
    }
}
