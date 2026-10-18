package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import android.util.Base64
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.File

/** Disposable emulator integration only. No owner credentials or test routes in the APK. */
class DevicePairingInstrumentation : Instrumentation() {
    private var phase = ""
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments); phase = arguments?.getString("phase").orEmpty(); start()
    }
    private fun invitation() = DeviceInvitation.parse(File(targetContext.filesDir,"pairing-invitation.json").readBytes())
    private fun manager() = DevicePairing(DeviceSessionStore(targetContext), { DeviceClient(it) })
    private fun reject(action: () -> Unit) {
        try { action() } catch (_: Exception) { return }
        error("Expected rejection")
    }
    private fun rejectTls(action: () -> Unit) {
        try { action() } catch (_: javax.net.ssl.SSLException) { return }
        error("Expected TLS identity rejection")
    }
    override fun onStart() {
        val report = Bundle()
        try {
            when (phase) {
                "security" -> security()
                "pair" -> pairThroughUi()
                "refresh" -> {
                    check(DeviceSessionStore(targetContext).load()!=null)
                    check(manager().check().state==PairingState.ASSOCIATED)
                    sealedAtRest()
                }
                "revoked" -> {
                    check(manager().check().state==PairingState.REASSOCIATE)
                    check(DeviceSessionStore(targetContext).load()==null)
                }
                "rotation-marker" -> {
                    val store=DeviceSessionStore(targetContext); val value=store.load() ?: error("Missing fixture")
                    store.save(SavedDevice(value.trust,value.tokens,value.refreshDeadline,refreshPending=true))
                }
                "after-marker" -> {
                    check(manager().check().state==PairingState.REASSOCIATE)
                    check(DeviceSessionStore(targetContext).load()==null)
                }
                "tamper" -> {
                    sealedAtRest()
                    val prefs=targetContext.getSharedPreferences("nova_device_session",0)
                    val raw=Base64.decode(prefs.getString("sealed",null),Base64.NO_WRAP)
                    raw[raw.lastIndex]=(raw.last().toInt() xor 1).toByte()
                    check(prefs.edit().putString("sealed",Base64.encodeToString(raw,Base64.NO_WRAP)).commit())
                    check(DeviceSessionStore(targetContext).load()==null)
                }
                "logout" -> { manager().forget(); check(DeviceSessionStore(targetContext).load()==null) }
                else -> error("Unknown test phase")
            }
            report.putString("nova_pairing", "passed"); report.putString("phase", phase)
            report.putInt("api", android.os.Build.VERSION.SDK_INT)
            finish(Activity.RESULT_OK,report)
        } catch (error: Throwable) {
            // Do not emit exception messages, which may include parsed secrets/JSON.
            report.putString("nova_pairing","failed");report.putString("phase",phase)
            report.putString("failure_type",error.javaClass.simpleName)
            report.putString("failure_at",error.stackTrace.firstOrNull { it.className.startsWith("com.novacinema") }?.let {
                it.className+":"+it.lineNumber
            })
            finish(Activity.RESULT_CANCELED,report)
        }
    }
    private fun security() {
        val parsed=invitation()
        reject { parsed.confirm("0".repeat(64)) }
        reject { DeviceInvitation.parse(ByteArray(16_385)) }
        val raw=JSONObject(File(targetContext.filesDir,"pairing-invitation.json").readText())
        reject { DeviceInvitation.parse(raw.put("client_origin","http://127.0.0.1:8920").toString().toByteArray()) }
        val trust=parsed.confirm(parsed.fingerprint)
        val unknownCertificate=File(targetContext.filesDir,"untrusted-certificate.der").readBytes()
        rejectTls { DeviceClient(ServerTrust(trust.origin,trust.serverId,unknownCertificate)).authorize("Wrong pin") }
        val wrongHost=DeviceInvitation.parse(File(targetContext.filesDir,"wrong-host-invitation.json").readBytes())
        rejectTls { DeviceClient(wrongHost.confirm(wrongHost.fingerprint)).authorize("Wrong hostname") }
        val wrongId=ServerTrust(trust.origin,"99999999-9999-4999-8999-999999999999",trust.certificateDer)
        reject { DevicePairing(DeviceSessionStore(targetContext),{DeviceClient(it)}).begin(wrongId,"Wrong server ID") }
        check(DeviceSessionStore(targetContext).load()==null)
    }
    private fun sealedAtRest() {
        val value=DeviceSessionStore(targetContext).load() ?: error("Missing session")
        val raw=File(targetContext.applicationInfo.dataDir,"shared_prefs/nova_device_session.xml").readText()
        check(!raw.contains(value.tokens.access) && !raw.contains(value.tokens.refresh))
        val sealed=targetContext.getSharedPreferences("nova_device_session",0).getString("sealed",null) ?: error("Missing ciphertext")
        val bytes=Base64.decode(sealed,Base64.NO_WRAP).toString(Charsets.ISO_8859_1)
        check(!bytes.contains(value.tokens.access) && !bytes.contains(value.tokens.refresh))
        // A new store instance must open the ciphertext with the existing non-exported key.
        check(DeviceSessionStore(targetContext).load()!!.tokens.refresh==value.tokens.refresh)
    }
    private fun views(root: View): List<View> = listOf(root) +
        if(root is ViewGroup) (0 until root.childCount).flatMap { views(root.getChildAt(it)) } else emptyList()

    private fun pairThroughUi() {
        val activity=startActivitySync(Intent(targetContext,DevicePairingActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as DevicePairingActivity
        val raw=File(targetContext.filesDir,"pairing-invitation.json").readBytes()
        try {
            waitForIdleSync()
            runOnMainSync { activity.reviewInvitation(raw) }
            runOnMainSync {
                val button=views(activity.window.decorView).filterIsInstance<Button>().first { it.text.toString().startsWith("Confirmei") }
                check(button.isFocusable && button.isEnabled)
                check(button.requestFocus() && button.hasFocus())
            }
            sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_DPAD_CENTER)
            var sent=false
            val deadline=System.currentTimeMillis()+120000
            while(System.currentTimeMillis()<deadline) {
                var texts=listOf<String>()
                runOnMainSync { texts=views(activity.window.decorView).filterIsInstance<TextView>().map { it.text.toString() } }
                val code=texts.firstOrNull { it.matches(Regex("[A-Z2-9]{4}-[A-Z2-9]{4}")) }
                if(code!=null && !sent) {
                    // The host test approves through the real administrative API; this is only a public user code.
                    sendStatus(1,Bundle().apply { putString("pair_code",code) });sent=true
                }
                if(texts.any { it.startsWith("Dispositivo associado e identidade confirmada") }) {
                    check(sent);sealedAtRest();return
                }
                Thread.sleep(150)
            }
            error("Pairing UI did not complete")
        } finally { runOnMainSync { activity.finish() } }
    }
}
