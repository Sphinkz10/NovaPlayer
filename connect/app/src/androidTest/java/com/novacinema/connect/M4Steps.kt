package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.util.Base64
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.File

class M4Steps(private val runner:Instrumentation) {
    private val context get()=runner.targetContext
    private fun main(action:()->Unit) {
        var failure:Throwable?=null
        runner.runOnMainSync { try { action() } catch(error:Throwable) { failure=error } }
        failure?.let { throw it }
    }
    private fun views(root:View):List<View> = listOf(root)+if(root is ViewGroup)
        (0 until root.childCount).flatMap { views(root.getChildAt(it)) } else emptyList()
    private fun waitUntil(timeout:Long=45000,action:()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+timeout
        while(android.os.SystemClock.uptimeMillis()<end) { if(action())return;Thread.sleep(100) };error("M4 condition timed out")
    }
    private fun click(activity:Activity,tag:String) {
        waitUntil {
            var ready=false
            main {
                val button=views(activity.window.decorView).filterIsInstance<Button>().firstOrNull { it.tag==tag }
                if(button!=null && activity.hasWindowFocus())ready=button.requestFocus() && button.hasFocus()
            };ready
        }
        runner.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_CENTER)
    }
    fun run() {
        val data=JSONObject(File(context.filesDir,"mfour-fixture.json").readText())
        val t=data.getJSONObject("tokens")
        DeviceSessionStore(context).save(SavedDevice(ServerTrust(data.string("origin"),data.string("server_id"),
            Base64.decode(data.string("certificate"),Base64.NO_WRAP)),
            DeviceTokens(t.string("access_token"),t.string("refresh_token"),t.string("device_id"),
                t.integer("expires_in"),t.integer("refresh_expires_in")),
            System.currentTimeMillis()+t.integer("refresh_expires_in")*1000L,accountId=data.string("account")))
        val client=MediaClient(context);val library=data.string("library");val item=data.string("item")
        check(client.page(library).items.single().id==item)
        check(client.page(library,search="absent").items.isEmpty())
        var denied=false
        try { client.page(data.string("other_library")) } catch(_:Exception) { denied=true }
        check(denied)
        val monitor=runner.addMonitor(PlayerActivity::class.java.name,null,false)
        val cinema=runner.startActivitySync(Intent(context,CinemaActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        var playback:PlayerActivity?=null
        try {
            runner.setInTouchMode(false)
            click(cinema,"cinema-library-$library");click(cinema,"cinema-item-$item");click(cinema,"cinema-play")
            playback=runner.waitForMonitorWithTimeout(monitor,30000) as? PlayerActivity ?: error("Player not opened")
            waitUntil { var ok=false;main { ok=playback!!.renderedFrame && playback!!.observedPosition>1000 };ok }
            var before=0L;main { before=playback!!.observedPosition }
            runner.sendKeyDownUpSync(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD)
            waitUntil(5000) { var ok=false;main { ok=playback!!.observedPosition>=before+9000 };ok }
            runner.sendKeyDownUpSync(KeyEvent.KEYCODE_MEDIA_PAUSE)
            main { playback!!.finish() };playback=null
            waitUntil { client.detail(library,item).position>=100000000 }
            val resumed=client.detail(library,item).position/10000
            playback=runner.startActivitySync(Intent(context,PlayerActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra("library",library).putExtra("item",item).putExtra("position",resumed)) as PlayerActivity
            waitUntil { var ok=false;main { ok=playback!!.renderedFrame && playback!!.observedPosition>=resumed };ok }
        } finally {
            main { playback?.finish();cinema.finish() };runner.removeMonitor(monitor)
        }
    }
}
