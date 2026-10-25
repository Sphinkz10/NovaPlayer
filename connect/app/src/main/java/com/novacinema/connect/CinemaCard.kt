package com.novacinema.connect

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.TextPaint
import android.text.TextUtils
import android.widget.Button

/** A real focusable Button: remote navigation and accessibility retain native semantics. */
internal class CinemaCard(context:Context,val item:CinemaItem):Button(context) {
    val artwork=CinemaArtwork(item.name)
    private val drawing=Paint(Paint.ANTI_ALIAS_FLAG)
    private val lettering=TextPaint(Paint.ANTI_ALIAS_FLAG)
    init {
        text=item.name;contentDescription=listOf(item.series,item.name,metadata()).filter { it.isNotBlank() }.joinToString(" · ")
        background=null;backgroundTintList=null;isAllCaps=false
        isFocusable=true;isFocusableInTouchMode=false;setPadding(0,0,0,0)
        setWillNotDraw(false);clipToOutline=false
    }
    private fun metadata()=when {
        item.type=="Episode" -> "T${item.season} · E${item.episode}"
        item.year>0 -> item.year.toString()
        else -> "Filme"
    }+(if(item.played)" · Visto" else if(item.position>0)" · Retomar" else "")
    override fun onFocusChanged(gain:Boolean,direction:Int,previous:android.graphics.Rect?) {
        super.onFocusChanged(gain,direction,previous)
        animate().scaleX(if(gain)1.035f else 1f).scaleY(if(gain)1.035f else 1f).setDuration(140).start()
        translationZ=if(gain)TvUi.dp(context,8).toFloat() else 0f;invalidate()
    }
    override fun drawableStateChanged() { super.drawableStateChanged();invalidate() }
    override fun onDraw(canvas:Canvas) {
        val inset=TvUi.dp(context,4).toFloat();val posterBottom=height-TvUi.dp(context,54).toFloat()
        artwork.setBounds(inset.toInt(),inset.toInt(),width-inset.toInt(),posterBottom.toInt())
        artwork.draw(canvas)
        if(item.position>0 && !item.played && item.runtime>0) {
            val fraction=(item.position.toDouble()/item.runtime).coerceIn(0.0,1.0).toFloat()
            drawing.color=0x99000000.toInt();canvas.drawRect(inset,posterBottom-4,width-inset,posterBottom,drawing)
            drawing.color=TvUi.accent;canvas.drawRect(inset,posterBottom-4,inset+(width-2*inset)*fraction,posterBottom,drawing)
        }
        if(isFocused || isPressed) {
            drawing.style=Paint.Style.STROKE;drawing.strokeWidth=TvUi.dp(context,2).toFloat();drawing.color=Color.WHITE
            canvas.drawRoundRect(RectF(inset-1,inset-1,width-inset+1,posterBottom+1),11f,11f,drawing)
            drawing.style=Paint.Style.FILL
        }
        lettering.color=TvUi.ink;lettering.textSize=android.util.TypedValue.applyDimension(android.util.TypedValue.COMPLEX_UNIT_SP,15f,resources.displayMetrics)
        lettering.typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL)
        val title=TextUtils.ellipsize(item.name,lettering,width-2*inset,TextUtils.TruncateAt.END).toString()
        canvas.drawText(title,inset,posterBottom+TvUi.dp(context,23),lettering)
        lettering.color=TvUi.muted;lettering.textSize=android.util.TypedValue.applyDimension(android.util.TypedValue.COMPLEX_UNIT_SP,12f,resources.displayMetrics)
        lettering.typeface=Typeface.create("sans-serif",Typeface.NORMAL)
        canvas.drawText(TextUtils.ellipsize(metadata(),lettering,width-2*inset,TextUtils.TruncateAt.END).toString(),
            inset,posterBottom+TvUi.dp(context,43),lettering)
    }
}
