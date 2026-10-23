package com.novacinema.connect

import android.app.Activity
import android.app.Instrumentation
import android.content.pm.ApplicationInfo
import android.os.Bundle
import android.os.SystemClock
import android.view.WindowManager
import java.io.File

/** Test APK only, synthetic LAN fixture screens only. Never captures credentials.
 * Production Activities keep FLAG_SECURE. Clear it just for this disposable
 * debug screenshot and restore it before returning, including on failure.
 */
class LabScreenshots(private val runner: Instrumentation) {
    private fun main(action:()->Unit) {
        var failure:Throwable?=null
        runner.runOnMainSync { try { action() } catch(error:Throwable) { failure=error } }
        failure?.let { throw it }
    }
    fun capture(activity: Activity, name: String) {
        check(runner.targetContext.packageName == "com.novacinema.connect.poc")
        check(runner.targetContext.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
        check(name in setOf("tv-home", "tv-libraries", "tv-catalogue", "tv-detail", "tv-player"))
        check(activity is CinemaActivity || activity is PlayerActivity || activity is MainActivity)
        var wasSecure = false
        var ready=false
        val focusDeadline=SystemClock.elapsedRealtime()+15000
        while(!ready && SystemClock.elapsedRealtime()<focusDeadline) {
            main {
                if(activity.hasWindowFocus() && !activity.isFinishing && !activity.isDestroyed) {
                    wasSecure = activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0
                    check(wasSecure)
                    activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    ready=true
                }
            }
            if(!ready)Thread.sleep(50)
        }
        check(ready) { "Screenshot window did not receive focus" }
        try {
            runner.waitForIdleSync(); Thread.sleep(300)
            // API 26 UiAutomation screenshots can return null after a display
            // override. Let the disposable host use Android's screencap service,
            // then acknowledge before restoring the secure window flag.
            runner.sendStatus(1, Bundle().apply { putString("screenshot_name", name) })
            val gate = File(runner.targetContext.filesDir, "lab-screenshot-gate.txt")
            val deadline = SystemClock.elapsedRealtime()+30000
            while (!gate.exists() || gate.readText() != name) {
                check(SystemClock.elapsedRealtime()<deadline) { "Screenshot acknowledgement unavailable" }
                Thread.sleep(50)
            }
        } finally {
            main {
                if (wasSecure) activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                check(activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
            }
        }
    }
}
