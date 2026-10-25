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
    private fun stage(value:String) { runner.sendStatus(1,android.os.Bundle().apply { putString("cinema_stage",value) }) }
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
    fun run(captureScreens:Boolean=false,installSession:Boolean=true) {
        val data=JSONObject(File(context.filesDir,"mfour-fixture.json").readText())
        val t=data.getJSONObject("tokens")
        if(installSession)DeviceSessionStore(context).save(SavedDevice(ServerTrust(data.string("origin"),data.string("server_id"),
            Base64.decode(data.string("certificate"),Base64.NO_WRAP)),
            DeviceTokens(t.string("access_token"),t.string("refresh_token"),t.string("device_id"),
                t.integer("expires_in"),t.integer("refresh_expires_in")),
            System.currentTimeMillis()+t.integer("refresh_expires_in")*1000L,accountId=data.string("account")))
        stage("api");val client=MediaClient(context);val library=data.string("library");val item=data.string("item")
        check(client.page(library).items.single().id==item)
        check(client.page(library,search="absent").items.isEmpty())
        check(client.page(library,kind="continue").items.isEmpty())
        check(client.image(library,item,client.session())?.width==160)
        var denied=false
        try { client.page(data.string("other_library")) } catch(_:Exception) { denied=true }
        check(denied)
        val monitor=runner.addMonitor(PlayerActivity::class.java.name,null,false)
        stage("home");val home=runner.startActivitySync(Intent(context,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        val catalogueMonitor=runner.addMonitor(CinemaActivity::class.java.name,null,false)
        runner.setInTouchMode(false)
        waitUntil { var ready=false;main { ready=views(home.window.decorView).filterIsInstance<Button>()
            .any { it.tag=="home-primary" && it.text.toString()=="Abrir biblioteca" } };ready }
        // The home shelf is actual account data. Open its title with the remote,
        // then use real Back to return to the catalogue, before the library path.
        waitUntil { var ready=false;main { ready=views(home.window.decorView)
            .any { it.tag=="home-content-loaded-$library" } };ready }
        if(captureScreens)LabScreenshots(runner).capture(home,"tv-home")
        click(home,"home-item-$item")
        val featured=runner.waitForMonitorWithTimeout(catalogueMonitor,30000) ?: error("Home title did not open detail")
        waitUntil { var ready=false;main { ready=views(featured.window.decorView).any { it.tag=="cinema-play" } };ready }
        runner.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        waitUntil { var ready=false;main { ready=views(featured.window.decorView)
            .any { it.tag=="cinema-item-$item" && it.hasFocus() } };ready }
        main { featured.finish() }
        // Foregrounding must re-authorize and reload the home, never reuse a
        // stale account's shelf or pin a previous network session in the UI.
        waitUntil { var ready=false;main { ready=home.hasWindowFocus() && views(home.window.decorView)
            .any { it.tag=="home-item-$item" && it.hasFocus() } };ready }
        click(home,"home-primary")
        val cinema=runner.waitForMonitorWithTimeout(catalogueMonitor,30000) ?: error("Home did not open catalogue")
        runner.removeMonitor(catalogueMonitor)
        var playback:PlayerActivity?=null
        fun capture(activity:Activity,tag:String,name:String) {
            if(!captureScreens)return
            waitUntil { var ready=false;main { ready=activity.hasWindowFocus() &&
                views(activity.window.decorView).filterIsInstance<Button>().any { it.tag==tag } };ready }
            LabScreenshots(runner).capture(activity,name)
        }
        try {
            runner.setInTouchMode(false)
            capture(cinema,"cinema-library-$library","tv-libraries")
            stage("library");click(cinema,"cinema-library-$library")
            capture(cinema,"cinema-item-$item","tv-catalogue")
            stage("detail");click(cinema,"cinema-item-$item")
            // Real Back must restore the catalogue and the selected card's focus.
            stage("back-focus");click(cinema,"cinema-back")
            waitUntil { var focused=false;main { focused=views(cinema.window.decorView)
                .any { it.tag=="cinema-item-$item" && it.hasFocus() } };focused }
            stage("detail");click(cinema,"cinema-item-$item")
            capture(cinema,"cinema-play","tv-detail")
            stage("player");click(cinema,"cinema-play")
            playback=runner.waitForMonitorWithTimeout(monitor,30000) as? PlayerActivity ?: error("Player not opened")
            waitUntil { var ok=false;main { ok=playback!!.renderedFrame && playback!!.observedPosition>1000 };ok }
            if(captureScreens)LabScreenshots(runner).capture(playback!!,"tv-player")
            var before=0L;main { before=playback!!.observedPosition }
            stage("seek");runner.sendKeyDownUpSync(KeyEvent.KEYCODE_MEDIA_FAST_FORWARD)
            try { waitUntil(5000) { var ok=false;main { ok=playback!!.observedPosition>=before+9000 };ok } }
            catch(error:Exception) {
                val state=android.os.Bundle()
                main { state.putBoolean("seekable",playback!!.observedSeekable);state.putLong("duration",playback!!.observedDuration)
                    state.putBoolean("has_player",playback!!.observedHasPlayer);state.putLong("before",before)
                    state.putLong("position",playback!!.observedPosition);state.putBoolean("window_focus",playback!!.hasWindowFocus()) }
                runner.sendStatus(1,state);throw error
            }
            stage("pause");runner.sendKeyDownUpSync(KeyEvent.KEYCODE_MEDIA_PAUSE)
            waitUntil { var paused=false;main { paused=!playback!!.observedPlaying };paused }
            stage("background");val settings=runner.startActivitySync(Intent(context,ConnectionActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            stage("foreground");main { settings.finish() }
            waitUntil { var paused=false;main { paused=playback!!.renderedFrame && !playback!!.observedPlaying };paused }
            var pausedAt=0L;main { pausedAt=playback!!.observedPosition }
            Thread.sleep(1200)
            main { check(!playback!!.observedPlaying && kotlin.math.abs(playback!!.observedPosition-pausedAt)<250) }
            stage("stop");main { playback!!.finish() };playback=null
            waitUntil { client.detail(library,item).position>=100000000 }
            val resumed=client.detail(library,item).position/10000
            check(client.page(library,kind="continue").items.single().id==item)
            stage("resume");playback=runner.startActivitySync(Intent(context,PlayerActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra("library",library).putExtra("item",item).putExtra("position",resumed)) as PlayerActivity
            waitUntil { var ok=false;main { ok=playback!!.renderedFrame && playback!!.observedPosition>=resumed };ok }
        } finally {
            main { playback?.finish();cinema.finish();home.finish() };runner.removeMonitor(monitor)
        }
    }
}
