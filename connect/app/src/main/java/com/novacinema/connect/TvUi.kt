package com.novacinema.connect

import android.app.Activity
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.view.Gravity
import android.view.View
import android.widget.*

/** One focus language for the remote, with no touch-only actions. */
internal object TvUi {
    val background = Color.rgb(9, 15, 27)
    val surface = Color.rgb(23, 35, 53)
    val ink = Color.rgb(238, 244, 252)
    val muted = Color.rgb(170, 187, 207)
    val accent = Color.rgb(109, 226, 216)
    fun dp(context: Context, value: Int) = (value * context.resources.displayMetrics.density).toInt()
    fun shape(color: Int, stroke: Int = Color.TRANSPARENT) = GradientDrawable().apply {
        setColor(color); cornerRadius = 14f; setStroke(3, stroke)
    }
    fun focusBackground() = StateListDrawable().apply {
        addState(intArrayOf(-android.R.attr.state_enabled), shape(Color.rgb(20, 27, 39)))
        addState(intArrayOf(android.R.attr.state_focused), shape(Color.rgb(30, 64, 79), accent))
        addState(intArrayOf(android.R.attr.state_pressed), shape(Color.rgb(30, 64, 79), accent))
        addState(intArrayOf(), shape(surface))
    }
    fun screen(activity: Activity, title: String, subtitle: String? = null): LinearLayout {
        activity.window.statusBarColor = background; activity.window.navigationBarColor = background
        val root = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(context, 40), dp(context, 24), dp(context, 40), dp(context, 28))
        }
        val scroll = ScrollView(activity).apply {
            setBackgroundColor(TvUi.background); isFillViewport = true; clipToPadding = false; addView(root)
        }
        activity.setContentView(scroll)
        label(root, "N O V A   /   C I N E M A", 13f, accent).setPadding(0, 0, 0, dp(activity, 10))
        label(root, title, 30f).typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        subtitle?.let { label(root, it, 16f, muted) }
        return root
    }
    fun label(root: LinearLayout, value: String, size: Float = 18f, color: Int = ink) = TextView(root.context).apply {
        text = value; textSize = size; setTextColor(color)
        setPadding(0, dp(context, 5), 0, dp(context, 8)); root.addView(this)
    }
    fun row(root: LinearLayout) = LinearLayout(root.context).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; root.addView(this)
    }
    fun style(button: Button): Button = button.apply {
        background = focusBackground(); backgroundTintList = null
        setTextColor(ColorStateList(arrayOf(intArrayOf(-android.R.attr.state_enabled), intArrayOf()), intArrayOf(muted, ink)))
        isAllCaps = false; textSize = 17f; gravity = Gravity.CENTER_VERTICAL or Gravity.START
        minHeight = dp(context, 52); minimumHeight = dp(context, 52)
        setPadding(dp(context, 18), dp(context, 10), dp(context, 18), dp(context, 10))
        isFocusable = true; isFocusableInTouchMode = false
    }
    fun button(root: LinearLayout, title: String, tagValue: String? = null, action: () -> Unit): Button {
        val button = style(Button(root.context)).apply { text = title; tag = tagValue; setOnClickListener { action() } }
        val horizontal = root.orientation == LinearLayout.HORIZONTAL
        root.addView(button, LinearLayout.LayoutParams(if (horizontal) 0 else -1, -2, if (horizontal) 1f else 0f).apply {
            setMargins(0, dp(root.context, 7), dp(root.context, if (horizontal) 10 else 0), dp(root.context, 3))
        })
        return button
    }
    fun field(root: LinearLayout, hintValue: String, value: String = "") = EditText(root.context).apply {
        hint = hintValue; setText(value); setSingleLine(); textSize = 18f
        setTextColor(ink); setHintTextColor(muted); backgroundTintList = ColorStateList.valueOf(accent)
        root.addView(this, LinearLayout.LayoutParams(-1, dp(context, 56)))
    }
    fun time(millis: Long): String {
        val minutes = millis.coerceAtLeast(0) / 60000
        return if (minutes >= 60) "${minutes / 60} h ${minutes % 60} min" else "$minutes min"
    }
    fun network(context: Context) = when {
        RemoteTailscaleRuntime.selected(context) -> "Tailscale"
        RemoteWireGuardRuntime.selected(context) -> "WireGuard"
        else -> "Rede local"
    }
}
