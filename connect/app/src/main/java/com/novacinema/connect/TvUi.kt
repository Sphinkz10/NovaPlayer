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
import android.view.WindowManager
import android.widget.*

/** One focus language for the remote, with no touch-only actions. */
internal object TvUi {
    val background = Color.rgb(16, 17, 20)
    val surface = Color.rgb(25, 27, 32)
    val ink = Color.rgb(244, 243, 247)
    val muted = Color.rgb(176, 178, 189)
    val accent = Color.rgb(200, 181, 255)
    data class Destination(val label:String,val tag:String,val selected:Boolean=false,val open:()->Unit)
    fun railWidth(activity:Activity)=if(activity.resources.configuration.screenWidthDp<900)132 else 156
    fun contentWidth(activity:Activity)=(activity.resources.configuration.screenWidthDp-railWidth(activity)-64).coerceAtLeast(240)
    fun dp(context: Context, value: Int) = (value * context.resources.displayMetrics.density).toInt()
    fun shape(color: Int, stroke: Int = Color.TRANSPARENT) = GradientDrawable().apply {
        setColor(color); cornerRadius = 14f; setStroke(3, stroke)
    }
    fun focusBackground() = StateListDrawable().apply {
        addState(intArrayOf(-android.R.attr.state_enabled), shape(Color.rgb(20, 27, 39)))
        addState(intArrayOf(android.R.attr.state_focused), shape(Color.rgb(55, 46, 73), accent))
        addState(intArrayOf(android.R.attr.state_pressed), shape(Color.rgb(55, 46, 73), accent))
        addState(intArrayOf(android.R.attr.state_selected), shape(Color.rgb(43, 37, 57)))
        addState(intArrayOf(), shape(surface))
    }
    /** TV chrome is deliberately quieter than the content. */
    fun stage(activity: Activity, section: String, navigation:List<Destination> = emptyList()): LinearLayout {
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
        activity.window.navigationBarColor = background
        val root=LinearLayout(activity).apply {
            orientation=LinearLayout.VERTICAL
            setPadding(dp(context,32),dp(context,20),dp(context,32),dp(context,24))
        }
        val scroll=ScrollView(activity).apply {
            background=GradientDrawable(GradientDrawable.Orientation.TL_BR,
                intArrayOf(Color.rgb(27,25,34),TvUi.background,TvUi.background))
            isFillViewport=true;clipToPadding=false;isVerticalScrollBarEnabled=false;addView(root)
        }
        if(navigation.isEmpty())activity.setContentView(scroll) else {
            val shell=LinearLayout(activity).apply { orientation=LinearLayout.HORIZONTAL;setBackgroundColor(TvUi.background) }
            val rail=LinearLayout(activity).apply {
                orientation=LinearLayout.VERTICAL
                setPadding(dp(context,16),dp(context,26),dp(context,12),dp(context,24))
                setBackgroundColor(Color.rgb(20,21,25))
            }
            label(rail,"NOVA",23f).apply { letterSpacing=0.16f;typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL) }
            label(rail,"C I N E M A",10f,accent).setPadding(0,0,0,dp(activity,30))
            navigation.forEach { destination ->
                action(rail,destination.label,destination.tag,destination.open).apply {
                    textSize=16f
                    layoutParams=LinearLayout.LayoutParams(-1,dp(activity,48)).apply { bottomMargin=dp(activity,8) }
                    setPadding(dp(activity,12),0,dp(activity,8),0)
                    isSelected=destination.selected
                    if(destination.selected) {
                        setTextColor(accent)
                    }
                }
            }
            val side=ScrollView(activity).apply { isVerticalScrollBarEnabled=false;isFillViewport=true;addView(rail) }
            shell.addView(side,LinearLayout.LayoutParams(dp(activity,railWidth(activity)),-1))
            shell.addView(scroll,LinearLayout.LayoutParams(0,-1,1f))
            activity.setContentView(shell)
        }
        val top=row(root).apply { setPadding(0,0,0,dp(context,22)) }
        label(top,if(navigation.isEmpty())"NOVA" else section.uppercase(java.util.Locale.ROOT),if(navigation.isEmpty())22f else 12f,if(navigation.isEmpty())ink else accent).apply {
            letterSpacing=0.18f;typeface=Typeface.create("sans-serif-black",Typeface.NORMAL)
            layoutParams=LinearLayout.LayoutParams(-2,-2)
        }
        if(navigation.isEmpty())label(top,"CINEMA",11f,accent).apply {
            letterSpacing=0.25f
            layoutParams=LinearLayout.LayoutParams(-2,-2).apply { leftMargin=dp(context,12) }
        }
        label(top,if(navigation.isEmpty())section else "O teu cinema, em casa",12f,muted).apply {
            gravity=Gravity.END
            layoutParams=LinearLayout.LayoutParams(0,-2,1f)
        }
        return root
    }
    fun heading(root:LinearLayout,value:String,size:Float=28f)=label(root,value,size).apply {
        typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL)
    }
    fun action(root:LinearLayout,title:String,tagValue:String?=null,action:()->Unit):Button {
        val button=style(Button(root.context)).apply { text=title;tag=tagValue;setOnClickListener { action() } }
        root.addView(button,LinearLayout.LayoutParams(-2,dp(root.context,48)).apply {
            setMargins(0,dp(root.context,6),dp(root.context,10),dp(root.context,6))
        })
        return button
    }
    fun screen(activity: Activity, title: String, subtitle: String? = null): LinearLayout {
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
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
        minHeight = dp(context, 48); minimumHeight = dp(context, 48)
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
