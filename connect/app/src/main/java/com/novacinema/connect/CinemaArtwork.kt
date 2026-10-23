package com.novacinema.connect

import android.graphics.*
import android.graphics.drawable.Drawable

/** A deterministic placeholder remains usable when artwork is missing or offline. */
internal class CinemaArtwork(private val title:String):Drawable() {
    var bitmap:Bitmap?=null
    private val paint=Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    override fun draw(canvas:Canvas) {
        val area=RectF(bounds);val path=Path().apply { addRoundRect(area,10f,10f,Path.Direction.CW) }
        val checkpoint=canvas.save();canvas.clipPath(path)
        val image=bitmap
        if(image!=null) {
            val scale=maxOf(area.width()/image.width,area.height()/image.height)
            val width=image.width*scale;val height=image.height*scale
            val target=RectF(area.centerX()-width/2,area.centerY()-height/2,area.centerX()+width/2,area.centerY()+height/2)
            paint.shader=null;canvas.drawBitmap(image,null,target,paint)
        } else {
            paint.shader=LinearGradient(0f,0f,area.width(),area.height(),intArrayOf(Color.rgb(30,68,88),TvUi.background),null,Shader.TileMode.CLAMP)
            canvas.drawRect(area,paint);paint.shader=null
            paint.color=TvUi.accent;paint.textAlign=Paint.Align.CENTER;paint.typeface=Typeface.create("sans-serif-light",Typeface.NORMAL)
            paint.textSize=area.width()*0.42f
            canvas.drawText(title.trim().take(1).uppercase(),area.centerX(),area.centerY()+paint.textSize/3,paint)
            paint.color=TvUi.muted;paint.textSize=area.width()*0.10f
            canvas.drawText("N O V A",area.centerX(),area.bottom-area.height()*0.1f,paint)
        }
        canvas.restoreToCount(checkpoint)
    }
    override fun setAlpha(alpha:Int) { paint.alpha=alpha }
    override fun setColorFilter(filter:ColorFilter?) { paint.colorFilter=filter }
    @Deprecated("Required Drawable compatibility method")
    override fun getOpacity()=PixelFormat.TRANSLUCENT
}
