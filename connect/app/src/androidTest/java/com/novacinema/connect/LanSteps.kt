package com.novacinema.connect

import android.app.Instrumentation
import android.content.Intent
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.*
import org.json.JSONObject
import java.io.File

class LanSteps(private val runner:Instrumentation) {
    private val context get()=runner.targetContext
    private fun main(action:()->Unit) {
        var error:Throwable?=null;runner.runOnMainSync { try { action() } catch(e:Throwable) { error=e } };error?.let { throw it }
    }
    private fun views(root:View):List<View> = listOf(root)+if(root is ViewGroup)(0 until root.childCount).flatMap { views(root.getChildAt(it)) }else emptyList()
    private fun waitUntil(action:()->Boolean) {
        val deadline=android.os.SystemClock.uptimeMillis()+45000
        while(android.os.SystemClock.uptimeMillis()<deadline) { if(action())return;Thread.sleep(100) };error("LAN test timed out")
    }
    private fun reject(action:()->Unit) { try { action() } catch(_:Exception) { return };error("Expected rejection") }
    fun run() {
        val fixture=JSONObject(File(context.filesDir,"lan-fixture.json").readText())
        val origin=fixture.string("origin");val pin=fixture.string("fingerprint")
        reject { DirectoryBootstrap.fetch(origin,"0".repeat(64)) }
        reject { DirectoryBootstrap.fetch(origin.replace("https:","http:"),pin) }
        val activity=runner.startActivitySync(Intent(context,DirectorySetupActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        try {
            runner.setInTouchMode(false)
            waitUntil {
                var focused=false
                main {
                    val all=views(activity.window.decorView)
                    all.filterIsInstance<EditText>().first { it.tag=="setup-origin" }.setText(origin)
                    all.filterIsInstance<EditText>().first { it.tag=="setup-fingerprint" }.setText(pin)
                    (activity.getSystemService(android.app.Activity.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager)
                        .hideSoftInputFromWindow(activity.window.decorView.windowToken,0)
                    val button=all.filterIsInstance<Button>().first { it.tag=="setup-confirm" }
                    focused=activity.hasWindowFocus() && button.requestFocus() && button.hasFocus()
                };focused
            }
            runner.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_CENTER)
            waitUntil { var done=false;main { done=views(activity.window.decorView).filterIsInstance<TextView>().any {
                it.text.toString().startsWith("Configuração guardada.") } };done }
            val loaded=DirectoryProfile.load(context)
            check(loaded.origin==origin && com.novacinema.connect.core.ServerTrust.fingerprint(loaded.certificateDer)==pin)
            reject { DirectorySetupStore(context).saveNew(JSONObject(DirectorySetupStore(context).load()!!.toString(Charsets.UTF_8))
                .put("public_key","A".repeat(43)).toString().toByteArray()) }
        } finally { main { activity.finish() } }
        M3Steps(runner).run("login")
        val saved=DeviceSessionStore(context).load() ?: error("LAN association missing")
        val library=fixture.string("library");val item=MediaClient(context).page(library).items.single()
        val player=runner.startActivitySync(Intent(context,PlayerActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            .putExtra("library",library).putExtra("item",item.id)) as PlayerActivity
        try { waitUntil { var rendered=false;main { rendered=player.renderedFrame && player.observedPosition>1000 };rendered } }
        finally { main { player.finish() } }
        check(DeviceSessionStore(context).load()!!.tokens.deviceId==saved.tokens.deviceId)
        val prefs=context.getSharedPreferences("nova_directory_setup",0)
        val sealed=android.util.Base64.decode(prefs.getString("sealed",null),android.util.Base64.NO_WRAP)
        sealed[sealed.lastIndex]=(sealed.last().toInt() xor 1).toByte()
        check(prefs.edit().putString("sealed",android.util.Base64.encodeToString(sealed,android.util.Base64.NO_WRAP)).commit())
        reject { DirectoryProfile.load(context) }
        reject { DirectorySetupStore(context).saveNew(DirectoryBootstrap.fetch(origin,pin)) }
    }
}
