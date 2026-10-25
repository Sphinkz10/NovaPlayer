package com.novacinema.connect

import android.app.Activity
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.widget.*

/** Home contains only content returned by the associated account, never demo titles. */
internal class CinemaHomeView(activity:Activity,openLibrary:()->Unit,connection:()->Unit,
    account:()->Unit,setup:()->Unit) {
    val root=TvUi.stage(activity,"Início")
    val status:TextView
    val primary:Button
    private val title:TextView
    private val description:TextView
    private val poster:ImageView
    private val shelf:LinearLayout
    private val section:TextView
    private val context=activity
    private var featured:String?=null
    init {
        root.setPadding(TvUi.dp(activity,48),TvUi.dp(activity,16),TvUi.dp(activity,48),TvUi.dp(activity,20))
        val menu=root.getChildAt(0) as LinearLayout
        menu.setPadding(0,0,0,TvUi.dp(activity,12))
        TvUi.action(menu,"Ligação","home-connection",connection)
        TvUi.action(menu,"Conta","home-account",account)
        TvUi.action(menu,"Configurar","home-setup",setup)
        val hero=FrameLayout(activity).apply {
            background=GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                intArrayOf(Color.rgb(29,48,60),Color.rgb(16,24,34))).apply { cornerRadius=TvUi.dp(activity,20).toFloat() }
            clipToOutline=true
        }
        root.addView(hero,LinearLayout.LayoutParams(-1,TvUi.dp(activity,240)).apply { topMargin=TvUi.dp(activity,12) })
        poster=ImageView(activity).apply { scaleType=ImageView.ScaleType.CENTER_CROP;alpha=0.7f;visibility=View.GONE }
        hero.addView(poster,FrameLayout.LayoutParams(TvUi.dp(activity,220),-1,Gravity.END))
        hero.addView(View(activity).apply {
            background=GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                intArrayOf(Color.rgb(29,48,60),0xf01d303c.toInt(),0x00101822))
        },FrameLayout.LayoutParams(-1,-1))
        val copy=LinearLayout(activity).apply {
            orientation=LinearLayout.VERTICAL
            gravity=Gravity.CENTER_VERTICAL
            setPadding(TvUi.dp(context,30),TvUi.dp(context,16),TvUi.dp(context,24),TvUi.dp(context,16))
        }
        hero.addView(copy,FrameLayout.LayoutParams(-1,-1))
        TvUi.label(copy,"O TEU ESPAÇO. O TEU CINEMA.",11f,TvUi.accent).apply { letterSpacing=0.17f }
        val textWidth=((activity.resources.configuration.screenWidthDp-96)*0.68).toInt().coerceIn(260,650)
        title=TvUi.heading(copy,"Uma boa história\ncomeça aqui.",32f).apply { maxLines=2;maxWidth=TvUi.dp(activity,textWidth) }
        description=TvUi.label(copy,"Entra na tua conta para descobrir os filmes e séries partilhados contigo.",15f,TvUi.muted).apply {
            maxLines=1;ellipsize=android.text.TextUtils.TruncateAt.END;maxWidth=TvUi.dp(activity,textWidth)
        }
        val actions=TvUi.row(copy)
        primary=TvUi.action(actions,"Entrar na NOVA","home-primary",openLibrary).apply { minWidth=TvUi.dp(activity,190) }
        status=TvUi.label(root,"A ler a configuração desta TV…",12f,TvUi.muted).apply {
            setPadding(0,TvUi.dp(context,8),0,TvUi.dp(context,8))
        }
        section=TvUi.heading(root,"Tudo pronto para a primeira sessão",20f)
        val scroll=HorizontalScrollView(activity).apply {
            isHorizontalScrollBarEnabled=false;clipToPadding=false;clipChildren=false
        }
        shelf=LinearLayout(activity).apply {
            orientation=LinearLayout.HORIZONTAL;clipChildren=false;clipToPadding=false
            setPadding(0,TvUi.dp(context,10),TvUi.dp(context,12),TvUi.dp(context,12))
        }
        scroll.addView(shelf);root.addView(scroll)
        TvUi.label(shelf,"Associa a TV uma vez. Depois, escolhe o que queres ver.",15f,TvUi.muted)
        primary.requestFocus()
    }
    fun preview(library:String,items:List<CinemaItem>,open:(CinemaItem)->Unit,artwork:(CinemaCard)->Unit) {
        shelf.removeAllViews();section.text="Na tua biblioteca"
        items.firstOrNull()?.let { feature(it,null) }
        if(items.isEmpty())TvUi.label(shelf,"A biblioteca ainda não tem títulos disponíveis.",15f,TvUi.muted)
        items.take(10).forEach { item ->
            val card=CinemaCard(context,item).apply {
                tag="home-item-${item.id}";setOnClickListener { open(item) }
                setOnFocusChangeListener { _,focused -> if(focused)feature(item,this.artwork.bitmap) }
            }
            shelf.addView(card,LinearLayout.LayoutParams(TvUi.dp(context,142),TvUi.dp(context,260)).apply {
                rightMargin=TvUi.dp(context,16)
            })
            artwork(card)
        }
        root.tag="home-content-loaded-$library"
    }
    private fun feature(item:CinemaItem,bitmap:android.graphics.Bitmap?) {
        featured=item.id;title.text=item.name
        description.text=item.overview.ifBlank { "Escolhe uma história e faz da sala o teu cinema." }
        poster.visibility=View.VISIBLE
        if(bitmap!=null)poster.setImageBitmap(bitmap) else poster.setImageDrawable(CinemaArtwork(item.name))
    }
    fun artworkLoaded(card:CinemaCard) { if(featured==card.item.id)feature(card.item,card.artwork.bitmap) }
    fun focusedItem()=(root.findFocus() as? CinemaCard)?.item?.id
    fun restoreFocus(id:String?) {
        if(id!=null)(0 until shelf.childCount).map { shelf.getChildAt(it) }
            .filterIsInstance<CinemaCard>().firstOrNull { it.item.id==id }?.requestFocus()
    }
    fun resetPreview() {
        root.tag=null;featured=null;poster.setImageDrawable(null);poster.visibility=View.GONE
        title.text="Uma boa história\ncomeça aqui."
        description.text="Entra na tua conta para descobrir os filmes e séries partilhados contigo."
        section.text="A tua biblioteca";shelf.removeAllViews()
    }
    fun unavailable() { section.text="A tua biblioteca";shelf.removeAllViews()
        TvUi.label(shelf,"Abre a biblioteca para verificar a ligação e continuar.",15f,TvUi.muted) }
}
