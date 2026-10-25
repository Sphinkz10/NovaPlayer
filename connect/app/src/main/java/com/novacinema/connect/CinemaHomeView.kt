package com.novacinema.connect

import android.app.Activity
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.*

/** All titles/artwork come from the associated account; the shell contains no demo catalogue. */
internal class CinemaHomeView(activity:Activity,openLibrary:()->Unit,search:()->Unit,connection:()->Unit,
    account:()->Unit,setup:()->Unit) {
    val root=TvUi.stage(activity,"Início",listOf(
        TvUi.Destination("Início","home-start",true) { focusPrimary() },
        TvUi.Destination("Bibliotecas","home-library",open=openLibrary),
        TvUi.Destination("Pesquisar","home-search",open=search),
        TvUi.Destination("Conta","home-account",open=account),
        TvUi.Destination("Ligação","home-connection",open=connection),
        TvUi.Destination("Configurar","home-setup",open=setup)))
    val status:TextView
    val primary:Button
    private val title:TextView
    private val metadata:TextView
    private val description:TextView
    private val poster:ImageView
    private val shelf:LinearLayout
    private val section:TextView
    private val context=activity
    private var featured:String?=null
    private var openTitle:((CinemaItem)->Unit)?=null
    init {
        (root.getChildAt(0) as LinearLayout).setPadding(0,0,0,TvUi.dp(activity,12))
        val hero=FrameLayout(activity).apply {
            background=GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                intArrayOf(Color.rgb(43,36,59),Color.rgb(24,26,33))).apply { cornerRadius=TvUi.dp(activity,16).toFloat() }
            clipToOutline=true
        }
        root.addView(hero,LinearLayout.LayoutParams(-1,TvUi.dp(activity,260)))
        poster=ImageView(activity).apply { scaleType=ImageView.ScaleType.CENTER_CROP;alpha=0.85f;visibility=View.GONE }
        val artworkWidth=(TvUi.contentWidth(activity)*0.37).toInt().coerceIn(160,390)
        hero.addView(poster,FrameLayout.LayoutParams(TvUi.dp(activity,artworkWidth),-1,Gravity.END))
        hero.addView(View(activity).apply {
            background=GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT,
                intArrayOf(Color.rgb(43,36,59),0xf02b243b.toInt(),0x102b243b))
        },FrameLayout.LayoutParams(-1,-1))
        val copy=LinearLayout(activity).apply {
            orientation=LinearLayout.VERTICAL;gravity=Gravity.CENTER_VERTICAL
            setPadding(TvUi.dp(context,26),TvUi.dp(context,18),TvUi.dp(context,20),TvUi.dp(context,18))
        }
        hero.addView(copy,FrameLayout.LayoutParams(-1,-1))
        val textWidth=(TvUi.contentWidth(activity)*0.66).toInt().coerceAtLeast(230)
        TvUi.label(copy,"O TEU ESPAÇO. O TEU CINEMA.",10f,TvUi.accent).apply {
            letterSpacing=0.12f;setPadding(0,0,0,TvUi.dp(context,10))
        }
        title=TvUi.heading(copy,"Uma boa história começa aqui.",30f).apply {
            maxLines=1;ellipsize=TextUtils.TruncateAt.END;maxWidth=TvUi.dp(context,textWidth);setPadding(0,0,0,TvUi.dp(context,7))
        }
        metadata=TvUi.label(copy,"NOVA CINEMA",12f,TvUi.accent).apply { setPadding(0,0,0,TvUi.dp(context,8)) }
        description=TvUi.label(copy,"Entra na tua conta para descobrir os filmes e séries partilhados contigo.",14f,TvUi.muted).apply {
            maxLines=2;ellipsize=TextUtils.TruncateAt.END;maxWidth=TvUi.dp(context,textWidth);setPadding(0,0,0,TvUi.dp(context,10))
        }
        primary=TvUi.action(TvUi.row(copy),"Entrar na NOVA","home-primary",openLibrary).apply { minWidth=TvUi.dp(activity,180) }
        status=TvUi.label(root,"A ler a configuração desta TV…",11f,TvUi.muted).apply { setPadding(0,TvUi.dp(context,9),0,TvUi.dp(context,6)) }
        section=TvUi.heading(root,"A tua biblioteca",19f).apply { setPadding(0,TvUi.dp(context,6),0,TvUi.dp(context,3)) }
        val scroll=HorizontalScrollView(activity).apply { isHorizontalScrollBarEnabled=false;clipToPadding=false;clipChildren=false }
        shelf=LinearLayout(activity).apply {
            orientation=LinearLayout.HORIZONTAL;clipChildren=false;clipToPadding=false
            setPadding(TvUi.dp(context,5),TvUi.dp(context,8),TvUi.dp(context,12),TvUi.dp(context,8))
        }
        scroll.addView(shelf);root.addView(scroll)
        TvUi.label(shelf,"Associa a TV uma vez. Depois, escolhe o que queres ver.",14f,TvUi.muted)
        primary.requestFocus()
    }
    private fun focusPrimary() { primary.requestFocus() }
    fun preview(library:String,items:List<CinemaItem>,open:(CinemaItem)->Unit,artwork:(CinemaCard)->Unit) {
        openTitle=open;shelf.removeAllViews();section.text="Na tua biblioteca"
        items.firstOrNull()?.let { feature(it,null) }
        if(items.isEmpty())TvUi.label(shelf,"A biblioteca ainda não tem títulos disponíveis.",14f,TvUi.muted)
        items.take(10).forEach { item ->
            val card=CinemaCard(context,item).apply {
                tag="home-item-${item.id}";setOnClickListener { open(item) }
                setOnFocusChangeListener { _,focused -> if(focused)feature(item,this.artwork.bitmap) }
            }
            shelf.addView(card,LinearLayout.LayoutParams(TvUi.dp(context,124),TvUi.dp(context,222)).apply { rightMargin=TvUi.dp(context,18) })
            artwork(card)
        }
        root.tag="home-content-loaded-$library"
    }
    private fun feature(item:CinemaItem,bitmap:android.graphics.Bitmap?) {
        featured=item.id;title.text=item.name
        metadata.text=listOfNotNull(item.year.takeIf { it>0 }?.toString(),
            if(item.type=="Episode")"T${item.season} · E${item.episode}" else "Filme",
            item.runtime.takeIf { it>0 }?.let { TvUi.time(it/10000) },if(item.played)"Visto" else null).joinToString(" · ")
        description.text=item.overview.ifBlank { "Escolhe uma história e faz da sala o teu cinema." }
        primary.text=if(item.position>0 && !item.played)"Continuar a ver  →" else "Ver detalhes  →"
        primary.setOnClickListener { openTitle?.invoke(item) }
        poster.visibility=View.VISIBLE
        if(bitmap!=null)poster.setImageBitmap(bitmap) else poster.setImageDrawable(CinemaArtwork(item.name))
    }
    fun artworkLoaded(card:CinemaCard) { if(featured==card.item.id)feature(card.item,card.artwork.bitmap) }
    fun focusedItem()=(root.findFocus() as? CinemaCard)?.item?.id
    fun restoreFocus(id:String?) {
        if(id!=null)(0 until shelf.childCount).map { shelf.getChildAt(it) }.filterIsInstance<CinemaCard>()
            .firstOrNull { it.item.id==id }?.requestFocus()
    }
    fun resetPreview() {
        root.tag=null;featured=null;openTitle=null;poster.setImageDrawable(null);poster.visibility=View.GONE
        title.text="Uma boa história começa aqui.";metadata.text="NOVA CINEMA"
        description.text="Entra na tua conta para descobrir os filmes e séries partilhados contigo."
        section.text="A tua biblioteca";shelf.removeAllViews()
    }
    fun unavailable() { section.text="A tua biblioteca";shelf.removeAllViews()
        TvUi.label(shelf,"Abre as bibliotecas para verificar a ligação e continuar.",14f,TvUi.muted) }
}
