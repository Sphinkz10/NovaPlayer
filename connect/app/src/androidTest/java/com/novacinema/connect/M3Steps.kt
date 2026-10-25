package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.view.KeyEvent
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.util.Base64
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.File

/** Credentials exist only in the isolated test fixture, never in production classes/assets. */
class M3Steps(private val runner:Instrumentation) {
    private val context get()=runner.targetContext
    private fun fixture()=JSONObject(File(context.filesDir,"mthree-fixture.json").readText())
    private fun profile()=DirectoryProfile.load(context)
    private fun manager()=DevicePairing(DeviceSessionStore(context),{DeviceClient(it)})
    private fun reject(action:()->Unit) { try { action() } catch(_:Exception) { return };error("Expected rejection") }
    private fun main(action:()->Unit) {
        var failure:Throwable?=null
        runner.runOnMainSync { try { action() } catch(error:Throwable) { failure=error } }
        failure?.let { throw it }
    }
    private fun views(root:View):List<View> = listOf(root)+if(root is ViewGroup)
        (0 until root.childCount).flatMap { views(root.getChildAt(it)) } else emptyList()
    private fun waitUntil(seconds:Long=30,action:()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+seconds*1000
        while(android.os.SystemClock.uptimeMillis()<end) { if(action())return;Thread.sleep(100) };error("Condition timed out")
    }
    private fun permissions() {
        val saved=DeviceSessionStore(context).load() ?: error("Missing session")
        check(saved.accountId==fixture().string("account"))
        check(manager().check().state==PairingState.ASSOCIATED)
        val allowed=DeviceClient(saved.trust).permissions(DeviceSessionStore(context).load()!!)
        check(allowed.map { it.first }==listOf(fixture().string("library")))
        val raw=File(context.applicationInfo.dataDir,"shared_prefs/nova_device_session.xml").readText()
        check(!raw.contains(saved.tokens.access) && !raw.contains(saved.tokens.refresh))
    }
    fun run(phase:String) {
        when(phase) {
            "security" -> {
                val data=fixture();val p=profile()
                check(canonical(JSONObject().put("z","Cinema · 😀").put("a",1))=="{\"a\":1,\"z\":\"Cinema \\u00b7 \\ud83d\\ude00\"}")
                reject { DirectoryProfile.parse(ByteArray(16385)) }
                val raw=JSONObject(File(context.filesDir,"nova-directory.json").readText())
                reject { DirectoryProfile.parse(raw.put("origin",p.origin.replace("https:","http:")).toString().toByteArray()) }
                val entry=DirectoryEntry.verify(data.getJSONObject("record"),p)
                DirectoryPins(context).accept(p,entry)
                val tampered=JSONObject(data.getJSONObject("record").toString())
                tampered.getJSONObject("payload").getJSONObject("descriptor").put("name","Changed")
                reject { DirectoryEntry.verify(tampered,p) }
                reject { DirectoryClient(DirectoryProfile(p.origin,p.certificateDer,data.string("wrong_key"))).login("alice",data.string("password")) }
                val wrong=DirectoryProfile.parse(data.getJSONObject("wrong_profile").toString().toByteArray())
                reject { DirectoryClient(wrong).login("alice",data.string("password")) }
            }
            "login","relogin","rotation" -> login(phase)
            "refresh" -> permissions()
            "rollback" -> {
                val data=fixture();val p=profile()
                reject { DirectoryPins(context).accept(p,DirectoryEntry.verify(data.getJSONObject("old_record"),p)) }
                reject { DirectoryPins(context).accept(p,DirectoryEntry.verify(data.getJSONObject("changed_key_record"),p)) }
                permissions()
            }
            "foreign" -> {
                val saved=DeviceSessionStore(context).load()!!;val data=fixture()
                val other=DirectoryEntry.verify(data.getJSONObject("foreign_record"),profile())
                reject { DeviceClient(other.trust).identity(saved.tokens.access) }
                reject { DeviceClient(saved.trust).authorizeBound("Wrong server",data.getJSONObject("foreign_assertion").toString()) }
                val bad=SavedDevice(saved.trust,saved.tokens,saved.refreshDeadline,accountId="99999999-9999-4999-8999-999999999999")
                var retained:SavedDevice?=bad
                val vault=object:DeviceVault {
                    override fun load()=retained
                    override fun save(value:SavedDevice) { retained=value }
                    override fun clear() { retained=null }
                }
                check(DevicePairing(vault,{DeviceClient(it)}).check().state==PairingState.SECURITY_ERROR)
                permissions()
            }
            "device-revoked","account-revoked" -> {
                check(manager().check().state==PairingState.REASSOCIATE)
                check(DeviceSessionStore(context).load()==null)
            }
            "unshared" -> {
                val data=fixture();val client=DirectoryClient(profile())
                try {
                    client.login("alice",data.string("password"));check(client.discover().isEmpty())
                    reject { client.assertion(DirectoryEntry.verify(data.getJSONObject("record"),profile())) }
                } finally { client.close() }
            }
            "pins-tampered" -> {
                val prefs=context.getSharedPreferences("nova_directory_pins",0)
                val raw=Base64.decode(prefs.getString("sealed",null),Base64.NO_WRAP)
                raw[raw.lastIndex]=(raw.last().toInt() xor 1).toByte()
                check(prefs.edit().putString("sealed",Base64.encodeToString(raw,Base64.NO_WRAP)).commit())
                reject { DirectoryPins(context).accept(profile(),DirectoryEntry.verify(fixture().getJSONObject("record"),profile())) }
            }
            else -> error("Unknown M3 phase")
        }
    }
    private fun login(phase:String) {
        val data=fixture();val before=DeviceSessionStore(context).load()?.tokens?.deviceId
        val monitor=runner.addMonitor(DevicePairingActivity::class.java.name,null,false)
        val activity=runner.startActivitySync(Intent(context,DirectoryActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        var child:Activity?=null
        try {
            runner.waitForIdleSync();runner.setInTouchMode(false)
            waitUntil { var focused=false;main { focused=activity.hasWindowFocus() };focused }
            main {
                val all=views(activity.window.decorView)
                all.filterIsInstance<EditText>().first { it.tag=="directory-username" }.setText("alice")
                val password=all.filterIsInstance<EditText>().first { it.tag=="directory-password" }
                password.setText(data.string("password"))
                (activity.getSystemService(Activity.INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(password.windowToken,0)
                check(all.filterIsInstance<Button>().first { it.text.toString().startsWith("Entrar e") }.requestFocus())
            }
            runner.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_CENTER)
            waitUntil {
                var found=false
                main {
                    val all=views(activity.window.decorView)
                    val entries=all.filterIsInstance<Button>().filter { it.tag?.toString()?.startsWith("directory-entry-")==true }
                    if(entries.isNotEmpty()) {
                        check(entries.size==1 && entries[0].tag=="directory-entry-"+data.string("entry"))
                        check(all.filterIsInstance<EditText>().first { it.tag=="directory-password" }.text.isEmpty())
                        check(entries[0].requestFocus());found=true
                    }
                };found
            }
            runner.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_CENTER)
            child=runner.waitForMonitorWithTimeout(monitor,30000) ?: error("Association did not open")
            var sent=false
            waitUntil(120) {
                var texts=listOf<String>()
                main { texts=views(child!!.window.decorView).filterIsInstance<TextView>().map { it.text.toString() } }
                val code=texts.firstOrNull { it.matches(Regex("[A-Z2-9]{4}-[A-Z2-9]{4}")) }
                if(code!=null && !sent) {
                    check(phase!="rotation")
                    runner.sendStatus(1,Bundle().apply { putString("pair_code",code) });sent=true
                }
                texts.any { it.startsWith("Bibliotecas autorizadas:") && it.contains(data.string("library_name")) }
            }
            if(phase=="rotation")check(!sent && DeviceSessionStore(context).load()!!.tokens.deviceId==before) else check(sent)
            permissions()
        } finally {
            runner.removeMonitor(monitor)
            main { child?.finish();activity.finish() }
        }
    }
}
