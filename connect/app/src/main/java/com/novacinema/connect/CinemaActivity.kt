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
    private fun screen(title:String,subtitle:String?=null) { root=TvUi.screen(this,title,subtitle) }
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
            screen("Escolhe a tua biblioteca",TvUi.network(this)+" · Conteúdo partilhado contigo")
            values.forEachIndexed { index,(id,name) ->
                val b=button(name,"cinema-library-$id") { library=id;libraryName=name;page(id,0) }
                if(index==0)b.requestFocus()
            }
            if(values.isEmpty())label("Ainda não tens bibliotecas atribuídas. O proprietário pode partilhá-las no NOVA Control.")
            val row=TvUi.row(root)
            TvUi.button(row,"Conta e associação") { startActivity(Intent(this,DevicePairingActivity::class.java)) }
            TvUi.button(row,"Ligação") { startActivity(Intent(this,ConnectionActivity::class.java)) }
            TvUi.button(row,"Início") { finish() }
        }
    }
    private fun page(lib:String,start:Int) {
        selected=null;offset=start
        work({val client=MediaClient(this);client.page(lib,start,search,kind) to client.session()}) { (data,saved) ->
            screen(libraryName,TvUi.network(this)+" · Página ${start/24+1}")
            val filters=TvUi.row(root)
            listOf("all" to "Todos","movies" to "Filmes","episodes" to "Episódios","continue" to "Continuar a ver").forEach { (key,name) ->
                TvUi.button(filters,(if(kind==key)"●  " else "")+name,"cinema-filter-$key") { kind=key;focusedItem=null;page(lib,0) }
            }
            val searchRow=TvUi.row(root)
            val query=TvUi.field(searchRow,"Pesquisar nesta biblioteca",search).apply { tag="cinema-search" }
            query.layoutParams=LinearLayout.LayoutParams(0,TvUi.dp(this,56),3f)
            fun submit() { search=query.text.toString().take(100);focusedItem=null
                (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).hideSoftInputFromWindow(query.windowToken,0)
                page(lib,0) }
            query.imeOptions=android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH
            query.setOnEditorActionListener { _,action,_ -> if(action==android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH) { submit();true } else false }
            TvUi.button(searchRow,"Pesquisar","cinema-search-submit") { submit() }
            val columns=if(resources.configuration.screenWidthDp>=700)4 else 2
            var preferred:Button?=null;var first:Button?=null
            data.items.chunked(columns).forEach { items ->
                val row=TvUi.row(root).apply { gravity=Gravity.TOP }
                items.forEach { item ->
                    val title=item.name+"\n"+when {
                        item.type=="Episode" -> "T${item.season} · E${item.episode}"
                        item.year>0 -> item.year.toString()
                        else -> "Filme"
                    }+when { item.position>0 && !item.played -> " · Retomar";item.played -> " · Visto";else -> "" }
                    val b=TvUi.button(row,title,"cinema-item-${item.id}") { focusedItem=item.id;detail(lib,item.id) }.apply {
                        textSize=15f;gravity=Gravity.CENTER;maxLines=3;ellipsize=android.text.TextUtils.TruncateAt.END
                        contentDescription=item.series.takeIf { it.isNotEmpty() }?.let { "$it · " }.orEmpty()+title.replace('\n',' ')
                        setOnFocusChangeListener { _,hasFocus -> if(hasFocus)focusedItem=item.id }
                        compoundDrawablePadding=TvUi.dp(context,8)
                    }
                    if(first==null)first=b
                    if(item.id==focusedItem)preferred=b
                    artwork(b,lib,item,saved)
                }
                repeat(columns-items.size) { row.addView(android.view.View(this),LinearLayout.LayoutParams(0,1,1f)) }
            }
            if(data.items.isEmpty())label(if(kind=="continue")"Ainda não há títulos para retomar nesta biblioteca." else "Nenhum título encontrado. Experimenta outra pesquisa ou categoria.")
            val navigation=TvUi.row(root)
            if(start>0)TvUi.button(navigation,"← Página anterior","cinema-previous") { focusedItem=null;page(lib,maxOf(0,start-24)) }
            data.next?.let { TvUi.button(navigation,"Página seguinte →","cinema-next") { focusedItem=null;page(lib,it) } }
            TvUi.button(navigation,"Bibliotecas","cinema-libraries") { libraries() }
            (preferred ?: first ?: query).requestFocus()
        }
    }
    private fun artwork(button:Button,lib:String,item:CinemaItem,saved:SavedDevice) {
        val current=generation
        val drawing=CinemaArtwork(item.name).apply { setBounds(0,0,TvUi.dp(this@CinemaActivity,116),TvUi.dp(this@CinemaActivity,154)) }
        button.setCompoundDrawables(null,drawing,null,null)
        images.execute {
            if(!foreground || current!=generation)return@execute
            val image=runCatching { MediaClient(this).image(lib,item.id,saved) }.getOrNull() ?: return@execute
            runOnUiThread {
                if(foreground && current==generation && !isDestroyed) { drawing.bitmap=image;drawing.invalidateSelf() }
            }
        }
    }
    private fun detail(lib:String,id:String) {
        selected=id
        work({val client=MediaClient(this);client.detail(lib,id) to client.session()}) { (item,saved) ->
            screen(item.name,item.series.takeIf { it.isNotEmpty() })
            val metadata=listOfNotNull(item.year.takeIf { it>0 }?.toString(),
                if(item.type=="Episode")"Temporada ${item.season} · Episódio ${item.episode}" else null,
                if(item.runtime>0)TvUi.time(item.runtime/10000) else null,if(item.played)"Visto" else null).joinToString(" · ")
            label(metadata)
            val resume=if(item.played)0 else item.position/10000
            fun play(position:Long) { startActivity(Intent(this,PlayerActivity::class.java)
                .putExtra("library",lib).putExtra("item",id).putExtra("position",position)) }
            val row=TvUi.row(root).apply { if(resources.configuration.screenWidthDp<600)orientation=LinearLayout.VERTICAL }
            val poster=TvUi.button(row,if(resume>0)"Retomar · ${TvUi.time(resume)}" else "Reproduzir","cinema-play") { play(resume) }
            poster.gravity=Gravity.CENTER;artwork(poster,lib,item,saved)
            val summary=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
            row.addView(summary,if(row.orientation==LinearLayout.HORIZONTAL)LinearLayout.LayoutParams(0,-2,3f).apply { setMargins(TvUi.dp(this@CinemaActivity,18),0,0,0) } else LinearLayout.LayoutParams(-1,-2))
            TvUi.label(summary,item.overview.ifBlank { "Este título ainda não tem sinopse." })
            if(resume>0)TvUi.button(summary,"Reproduzir desde o início","cinema-restart") { play(0) }
            TvUi.label(summary,"${TvUi.network(this)} · Qualidade original. Áudio e legendas disponíveis no leitor.",15f,TvUi.muted)
            TvUi.button(summary,"Voltar aos títulos","cinema-back") { page(lib,offset) }
            poster.requestFocus()
        }
    }
    @Deprecated("Platform Back supports API 26")
    override fun onBackPressed() { val lib=library
        if(selected!=null && lib!=null)page(lib,offset) else if(lib!=null)libraries() else super.onBackPressed() }
}
