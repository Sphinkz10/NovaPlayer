package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.*
import com.novacinema.connect.core.SavedDevice
import java.util.concurrent.Executors
import java.util.concurrent.ThreadPoolExecutor

/** Account-scoped TV catalogue. Each page is re-authorized after foregrounding. */
class CinemaActivity:Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private val images=Executors.newFixedThreadPool(2) as ThreadPoolExecutor
    private lateinit var root:LinearLayout
    @Volatile private var generation=0
    @Volatile private var foreground=false
    private var library:String?=null
    private var libraryName=""
    private var search=""
    private var kind="all"
    private var selected:String?=null
    private var offset=0
    private var focusedItem:String?=null
    override fun onCreate(state:Bundle?) {
        super.onCreate(state);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        library=state?.getString("library");libraryName=state?.getString("libraryName").orEmpty()
        search=state?.getString("search").orEmpty();kind=state?.getString("kind") ?: "all"
        selected=state?.getString("selected");offset=state?.getInt("offset") ?: 0;focusedItem=state?.getString("focus")
        if(state==null) {
            library=intent.getStringExtra("library")?.takeIf { mediaId.matches(it) }
            libraryName=intent.getStringExtra("libraryName").orEmpty().take(200)
            selected=intent.getStringExtra("selected")?.takeIf { mediaId.matches(it) && library!=null }
            focusedItem=selected
        }
    }
    override fun onStart() { super.onStart();foreground=true;val lib=library
        if(lib==null)libraries() else selected?.let { detail(lib,it) } ?: page(lib,offset) }
    override fun onStop() { foreground=false;generation++;images.queue.clear();super.onStop() }
    override fun onDestroy() { io.shutdownNow();images.shutdownNow();super.onDestroy() }
    override fun onSaveInstanceState(out:Bundle) {
        out.putString("library",library);out.putString("libraryName",libraryName)
        out.putString("search",search);out.putString("kind",kind);out.putString("selected",selected)
        out.putInt("offset",offset);out.putString("focus",focusedItem);super.onSaveInstanceState(out)
    }
    private fun screen(title:String,subtitle:String?=null) {
        root=TvUi.stage(this,"Biblioteca");TvUi.heading(root,title)
        subtitle?.let { TvUi.label(root,it,14f,TvUi.muted) }
    }
    private fun label(value:String,size:Float=18f)=TvUi.label(root,value,size)
    private fun button(value:String,tagValue:String?=null,action:()->Unit)=TvUi.button(root,value,tagValue,action)
    private fun <T> work(load:()->T,render:(T)->Unit) {
        val current=++generation;images.queue.clear()
        screen("A abrir o teu cinema",TvUi.network(this));label("A verificar acesso e carregar os títulos…")
        io.execute {
            val result=runCatching(load)
            runOnUiThread {
                if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                result.fold(render) {
                    screen("Não foi possível abrir a biblioteca")
                    label("Confirma a ligação ao servidor e as permissões desta conta. Podes tentar novamente sem apagar a associação.")
                    button("Tentar novamente","cinema-retry") { val lib=library
                        if(lib==null)libraries() else selected?.let { detail(lib,it) } ?: page(lib,offset) }.requestFocus()
                    button("Ver ligação","cinema-connection") { startActivity(Intent(this,ConnectionActivity::class.java)) }
                    button("Conta e associação") { startActivity(Intent(this,DevicePairingActivity::class.java)) }
                    button("Voltar") { finish() }
                }
            }
        }
    }
    private fun libraries() {
        library=null;selected=null;offset=0;focusedItem=null;search="";kind="all"
        work({val client=MediaClient(this);val saved=client.session();DeviceClient(saved.trust).permissions(saved)}) { values ->
            screen("As tuas bibliotecas","Escolhe o que te apetece ver.")
            var row=TvUi.row(root)
            values.forEachIndexed { index,(id,name) ->
                if(index>0 && index%2==0)row=TvUi.row(root)
                val b=TvUi.button(row,"$name\nExplorar biblioteca  →","cinema-library-$id") { library=id;libraryName=name;page(id,0) }.apply {
                    minHeight=TvUi.dp(context,112);textSize=21f
                }
                if(index==0)b.requestFocus()
            }
            if(values.size%2==1)row.addView(android.view.View(this),LinearLayout.LayoutParams(0,1,1f))
            if(values.isEmpty())label("Ainda não tens bibliotecas atribuídas. O proprietário pode partilhá-las no NOVA Control.")
            val navigation=TvUi.row(root)
            TvUi.action(navigation,"Conta") { startActivity(Intent(this,DevicePairingActivity::class.java)) }
            TvUi.action(navigation,"Ligação") { startActivity(Intent(this,ConnectionActivity::class.java)) }
            TvUi.action(navigation,"← Início") { finish() }
        }
    }
    private fun page(lib:String,start:Int) {
        selected=null;offset=start
        work({val client=MediaClient(this);client.page(lib,start,search,kind) to client.session()}) { (data,saved) ->
            screen(libraryName,"Os teus filmes e séries")
            val filters=TvUi.row(root)
            listOf("all" to "Todos","movies" to "Filmes","episodes" to "Episódios","continue" to "Continuar a ver").forEach { (key,name) ->
                TvUi.action(filters,(if(kind==key)"●  " else "")+name,"cinema-filter-$key") { kind=key;focusedItem=null;page(lib,0) }
            }
            val searchRow=TvUi.row(root)
            val query=TvUi.field(searchRow,"Pesquisar nesta biblioteca",search).apply { tag="cinema-search" }
            query.layoutParams=LinearLayout.LayoutParams(0,TvUi.dp(this,48),1f)
            fun submit() { search=query.text.toString().take(100);focusedItem=null
                (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).hideSoftInputFromWindow(query.windowToken,0)
                page(lib,0) }
            query.imeOptions=android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH
            query.setOnEditorActionListener { _,action,_ -> if(action==android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH) { submit();true } else false }
            TvUi.action(searchRow,"Pesquisar","cinema-search-submit") { submit() }
            val available=(resources.configuration.screenWidthDp-96).coerceAtLeast(240)
            val columns=(available/152).coerceIn(2,7)
            val cardHeight=((available-(columns-1)*16)/columns*1.45+54).toInt()
            var preferred:Button?=null;var first:Button?=null
            data.items.chunked(columns).forEach { items ->
                val row=TvUi.row(root).apply { gravity=Gravity.TOP;clipChildren=false;clipToPadding=false }
                items.forEachIndexed { index,item ->
                    val b=CinemaCard(this,item).apply {
                        tag="cinema-item-${item.id}";setOnClickListener { focusedItem=item.id;detail(lib,item.id) }
                        setOnFocusChangeListener { _,hasFocus -> if(hasFocus)focusedItem=item.id }
                    }
                    row.addView(b,LinearLayout.LayoutParams(0,TvUi.dp(this,cardHeight),1f).apply {
                        setMargins(0,TvUi.dp(this@CinemaActivity,12),TvUi.dp(this@CinemaActivity,if(index==columns-1)0 else 16),TvUi.dp(this@CinemaActivity,12))
                    })
                    if(first==null)first=b
                    if(item.id==focusedItem)preferred=b
                    artwork(b,b.artwork,lib,item,saved)
                }
                (items.size until columns).forEach { index ->
                    row.addView(android.view.View(this),LinearLayout.LayoutParams(0,1,1f).apply {
                        rightMargin=TvUi.dp(this@CinemaActivity,if(index==columns-1)0 else 16)
                    })
                }
            }
            if(data.items.isEmpty())label(if(kind=="continue")"Ainda não há títulos para retomar nesta biblioteca." else "Nenhum título encontrado. Experimenta outra pesquisa ou categoria.")
            val navigation=TvUi.row(root)
            if(start>0)TvUi.action(navigation,"← Anterior","cinema-previous") { focusedItem=null;page(lib,maxOf(0,start-24)) }
            data.next?.let { TvUi.action(navigation,"Seguinte →","cinema-next") { focusedItem=null;page(lib,it) } }
            TvUi.action(navigation,"← Bibliotecas","cinema-libraries") { libraries() }
            TvUi.label(navigation,"Página ${start/24+1}",12f,TvUi.muted)
            (preferred ?: first ?: query).requestFocus()
        }
    }
    private fun artwork(view:android.view.View,drawing:CinemaArtwork,lib:String,item:CinemaItem,saved:SavedDevice) {
        val current=generation
        images.execute {
            if(!foreground || current!=generation)return@execute
            val image=runCatching { MediaClient(this).image(lib,item.id,saved) }.getOrNull() ?: return@execute
            runOnUiThread {
                if(foreground && current==generation && !isDestroyed) { drawing.bitmap=image;drawing.invalidateSelf();view.invalidate() }
            }
        }
    }
    private fun detail(lib:String,id:String) {
        selected=id
        work({val client=MediaClient(this);client.detail(lib,id) to client.session()}) { (item,saved) ->
            root=TvUi.stage(this,"Detalhe")
            val metadata=listOfNotNull(item.year.takeIf { it>0 }?.toString(),
                if(item.type=="Episode")"Temporada ${item.season} · Episódio ${item.episode}" else null,
                if(item.runtime>0)TvUi.time(item.runtime/10000) else null,if(item.played)"Visto" else null).joinToString(" · ")
            val resume=if(item.played)0 else item.position/10000
            fun play(position:Long) { startActivity(Intent(this,PlayerActivity::class.java)
                .putExtra("library",lib).putExtra("item",id).putExtra("position",position)) }
            val row=TvUi.row(root).apply { gravity=Gravity.TOP;if(resources.configuration.screenWidthDp<540)orientation=LinearLayout.VERTICAL }
            val drawing=CinemaArtwork(item.name)
            val poster=ImageView(this).apply { setImageDrawable(drawing);scaleType=ImageView.ScaleType.FIT_XY;importantForAccessibility=android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO }
            row.addView(poster,LinearLayout.LayoutParams(TvUi.dp(this,190),TvUi.dp(this,282)))
            artwork(poster,drawing,lib,item,saved)
            val summary=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
            row.addView(summary,if(row.orientation==LinearLayout.HORIZONTAL)LinearLayout.LayoutParams(0,-2,1f).apply { setMargins(TvUi.dp(this@CinemaActivity,30),0,0,0) } else LinearLayout.LayoutParams(-1,-2))
            item.series.takeIf { it.isNotEmpty() }?.let { TvUi.label(summary,it,14f,TvUi.accent) }
            TvUi.heading(summary,item.name,32f)
            TvUi.label(summary,metadata,14f,TvUi.muted)
            TvUi.label(summary,item.overview.ifBlank { "Este título ainda não tem sinopse." },17f).apply { maxLines=7;ellipsize=android.text.TextUtils.TruncateAt.END }
            val actions=TvUi.row(summary)
            val playButton=TvUi.action(actions,if(resume>0)"▶  Retomar · ${TvUi.time(resume)}" else "▶  Reproduzir","cinema-play") { play(resume) }
            if(resume>0)TvUi.action(actions,"Do início","cinema-restart") { play(0) }
            TvUi.label(summary,"Qualidade original · Áudio e legendas no leitor",12f,TvUi.muted)
            TvUi.action(summary,"← Voltar aos títulos","cinema-back") { page(lib,offset) }
            playButton.requestFocus()
        }
    }
    @Deprecated("Platform Back supports API 26")
    override fun onBackPressed() { val lib=library
        if(selected!=null && lib!=null)page(lib,offset) else if(lib!=null)libraries() else super.onBackPressed() }
}
