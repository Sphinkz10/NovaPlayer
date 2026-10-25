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
    /** Handle only Android's observed first-use fullscreen tutorial, never VPN consent. */
    private fun fullscreenHint() {
        val automation=runner.uiAutomation
        automation.serviceInfo=automation.serviceInfo.apply {
            flags=flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                android.accessibilityservice.AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
        }
        val root=automation.rootInActiveWindow ?: return
        if(root.packageName?.toString() !in setOf("android","com.android.systemui"))return
        val marker=root.findAccessibilityNodeInfosByViewId("android:id/immersive_cling_icon")
        val buttons=root.findAccessibilityNodeInfosByViewId("android:id/ok")
        if(marker.isNotEmpty() && buttons.size==1 && buttons[0].isClickable && buttons[0].isEnabled) {
            if(buttons[0].performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK))
                runner.sendStatus(1,Bundle().apply { putString("fullscreen_hint","dismissed") })
        }
    }
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
            if(!ready) {
                if(activity is PlayerActivity)fullscreenHint()
                Thread.sleep(50)
            }
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
