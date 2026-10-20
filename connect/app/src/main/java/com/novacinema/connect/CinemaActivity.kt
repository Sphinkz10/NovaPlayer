package com.novacinema.connect

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import android.widget.*
import java.util.concurrent.Executors

/** Minimal local Cinema journey, using only the account's NOVA media surface. */
class CinemaActivity:Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private lateinit var root:LinearLayout
    private var generation=0
    private var foreground=false
    private var library:String?=null
    private var libraryName=""
    private var search=""
    private var kind="all"
    private var selected:String?=null
    override fun onCreate(state:Bundle?) {
        super.onCreate(state);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        library=state?.getString("library");libraryName=state?.getString("libraryName").orEmpty()
        search=state?.getString("search").orEmpty();kind=state?.getString("kind") ?: "all"
        selected=state?.getString("selected")
    }
    override fun onStart() { super.onStart();foreground=true;val lib=library
        if(lib==null)libraries() else selected?.let { detail(lib,it) } ?: page(lib,0) }
    override fun onStop() { foreground=false;generation++;super.onStop() }
    override fun onDestroy() { io.shutdownNow();super.onDestroy() }
    override fun onSaveInstanceState(out:Bundle) {
        out.putString("library",library);out.putString("libraryName",libraryName)
        out.putString("search",search);out.putString("kind",kind);out.putString("selected",selected);super.onSaveInstanceState(out)
    }
    private fun screen(title:String) {
        root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(44,28,44,28) }
        setContentView(ScrollView(this).apply { addView(root) });label(title,28f)
    }
    private fun label(value:String,size:Float=20f)=TextView(this).apply { text=value;textSize=size;root.addView(this) }
    private fun button(value:String,tagValue:String?=null,action:()->Unit)=Button(this).apply {
        text=value;tag=tagValue;isFocusable=true;setOnClickListener { action() };root.addView(this)
    }
    private fun <T> work(load:()->T,render:(T)->Unit) {
        val current=++generation
        screen("NOVA Cinema");label("A carregar…")
        io.execute {
            val result=runCatching(load)
            runOnUiThread {
                if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                result.fold(render) {
                    screen("NOVA Cinema · Ligação indisponível")
                    label("Verifica a ligação ao servidor e as permissões desta conta. A associação foi preservada quando possível.")
                    button("Tentar novamente") { val lib=library;if(lib==null)libraries() else page(lib,0) }.requestFocus()
                    button("Associação e conta") { startActivity(Intent(this,DevicePairingActivity::class.java)) }
                    button("Voltar") { finish() }
                }
            }
        }
    }
    private fun libraries() {
        library=null;selected=null
        work({val client=MediaClient(this);val saved=client.session();DeviceClient(saved.trust).permissions(saved)}) { values ->
            screen("NOVA Cinema · Bibliotecas")
            values.forEachIndexed { index,(id,name) ->
                val b=button(name,"cinema-library-$id") { library=id;libraryName=name;page(id,0) }
                if(index==0)b.requestFocus()
            }
            if(values.isEmpty())label("Sem bibliotecas atribuídas. Contacta o proprietário.")
            button("Conta e associação") { startActivity(Intent(this,DevicePairingActivity::class.java)) }
            button("Voltar") { finish() }
        }
    }
    private fun page(lib:String,start:Int) {
        selected=null
        work({MediaClient(this).page(lib,start,search,kind)}) { data ->
            screen("NOVA Cinema · $libraryName")
            val query=EditText(this).apply { hint="Pesquisar títulos";setSingleLine();setText(search);maxLines=1;root.addView(this) }
            button("Pesquisar") { search=query.text.toString().take(100);page(lib,0) }
            button("Todos · Filmes · Episódios") {
                kind=when(kind) { "all"->"movies";"movies"->"episodes";else->"all" };page(lib,0)
            }
            label(when(kind) { "movies"->"Filmes";"episodes"->"Episódios";else->"Todos os títulos" })
            data.items.forEachIndexed { index,item ->
                val title=(if(item.series.isNotEmpty())item.series+" · " else "")+item.name+
                    (if(item.year>0)" (${item.year})" else "")+(if(item.position>0)" · Retomar" else "")
                val b=button(title,"cinema-item-${item.id}") { detail(lib,item.id) }
                if(index==0)b.requestFocus()
            }
            if(data.items.isEmpty())label("Nenhum título encontrado nesta biblioteca.")
            data.next?.let { button("Página seguinte") { page(lib,it) } }
            if(start>0)button("Página anterior") { page(lib,maxOf(0,start-24)) }
            button("Escolher biblioteca") { libraries() }
        }
    }
    private fun detail(lib:String,id:String) {
        selected=id
        work({MediaClient(this).detail(lib,id)}) { item ->
            screen(item.name);if(item.series.isNotEmpty())label(item.series)
            label("${item.year.takeIf { it>0 } ?: ""} · ${item.runtime/600000000} min")
            label(item.overview)
            val resume=item.position/10000
            fun play(position:Long) { startActivity(Intent(this,PlayerActivity::class.java)
                .putExtra("library",lib).putExtra("item",id).putExtra("position",position)) }
            button(if(resume>0)"Retomar aos ${resume/1000}s" else "Reproduzir","cinema-play") { play(resume) }.requestFocus()
            if(resume>0)button("Reproduzir desde o início") { play(0) }
            label("Direct Play local. Áudio e legendas incorporados dependem dos formatos suportados pelo aparelho.")
            button("Voltar aos títulos") { page(lib,0) }
        }
    }
    @Deprecated("Platform Back supports the API 26 laboratory baseline")
    override fun onBackPressed() { val lib=library
        if(selected!=null && lib!=null)page(lib,0) else if(lib!=null)libraries() else super.onBackPressed() }
}
