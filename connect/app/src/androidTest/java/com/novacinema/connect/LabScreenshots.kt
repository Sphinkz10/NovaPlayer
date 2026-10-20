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
    fun capture(activity: Activity, name: String) {
        check(runner.targetContext.packageName == "com.novacinema.connect.poc")
        check(runner.targetContext.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0)
        check(name in setOf("tv-libraries", "tv-catalogue", "tv-detail", "tv-player"))
        check(activity is CinemaActivity || activity is PlayerActivity)
        var wasSecure = false
        runner.runOnMainSync {
            check(activity.hasWindowFocus())
            wasSecure = activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0
            check(wasSecure)
            activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
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
            runner.runOnMainSync {
                if (wasSecure) activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                check(activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
            }
        }
    }
}
