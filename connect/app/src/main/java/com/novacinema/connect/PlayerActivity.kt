package com.novacinema.connect

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.widget.*
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.DataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import androidx.media3.ui.TrackSelectionDialogBuilder
import java.util.concurrent.Executors

/** Foreground playback only. Stop releases codecs, connections and the display wake lock. */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
class PlayerActivity:Activity() {
    private val io=Executors.newSingleThreadExecutor()
    private val handler=Handler(Looper.getMainLooper())
    private var player:ExoPlayer?=null
    private lateinit var view:PlayerView
    private lateinit var status:TextView
    private lateinit var library:String
    private lateinit var item:String
    private var position=0L
    private var generation=0
    private var foreground=false
    private var eventBusy=false
    internal var renderedFrame=false
        private set
    internal val observedPosition:Long get()=player?.currentPosition ?: position
    private val heartbeat=object:Runnable {
        override fun run() {
            if(!foreground)return
            val p=player ?: return
            report("progress",p.currentPosition,!p.isPlaying)
            handler.postDelayed(this,10000)
        }
    }
    override fun onCreate(state:Bundle?) {
        super.onCreate(state);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        library=intent.getStringExtra("library").orEmpty();item=intent.getStringExtra("item").orEmpty()
        if(!mediaId.matches(library) || !mediaId.matches(item)) { finish();return }
        position=state?.getLong("position") ?: intent.getLongExtra("position",0).coerceAtLeast(0)
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        status=TextView(this).apply { textSize=18f;setPadding(24,8,24,8);root.addView(this) }
        view=PlayerView(this).apply { useController=true;controllerShowTimeoutMs=5000
            root.addView(this,LinearLayout.LayoutParams(-1,0,1f)) }
        val controls=LinearLayout(this)
        fun button(title:String,action:()->Unit)=Button(this).apply { text=title;setOnClickListener { action() };controls.addView(this) }
        button("Áudio") {
            player?.let { TrackSelectionDialogBuilder(this,"Áudio",it,androidx.media3.common.C.TRACK_TYPE_AUDIO).build().show() }
        }
        button("Legendas") {
            player?.let { TrackSelectionDialogBuilder(this,"Legendas",it,androidx.media3.common.C.TRACK_TYPE_TEXT).build().show() }
        }
        button("Tentar novamente") { open() }
        button("Voltar") { finish() }
        root.addView(controls);setContentView(root);view.requestFocus()
    }
    override fun onStart() { super.onStart();foreground=true;if(::view.isInitialized)open() }
    override fun onSaveInstanceState(out:Bundle) { out.putLong("position",observedPosition);super.onSaveInstanceState(out) }
    override fun onStop() {
        foreground=false;generation++;handler.removeCallbacks(heartbeat)
        player?.let { position=it.currentPosition;report("stop",position,true,final=true) }
        release();super.onStop()
    }
    override fun onDestroy() { io.shutdown();super.onDestroy() }
    private fun release() {
        if(::view.isInitialized) { view.player=null;view.keepScreenOn=false }
        player?.release();player=null
    }
    private fun open() {
        handler.removeCallbacks(heartbeat)
        player?.let { position=it.currentPosition };release();renderedFrame=false
        status.text="A verificar título e autorização…";val current=++generation;val requestedPosition=position
        io.execute {
            val ready=runCatching {
                val client=MediaClient(this);val detail=client.detail(library,item)
                val resolved=if(detail.runtime>0)requestedPosition.coerceAtMost(detail.runtime/10000) else requestedPosition
                client.event(library,item,"start",resolved,false)
                client.session().trust.origin to resolved
            }
            runOnUiThread {
                if(!foreground || current!=generation || isDestroyed)return@runOnUiThread
                ready.fold({ (origin,resolved) ->
                    position=resolved
                    val p=ExoPlayer.Builder(this).build();player=p;view.player=p;view.keepScreenOn=true
                    val source=ProgressiveMediaSource.Factory(DataSource.Factory { NovaMediaSource(this) })
                        .createMediaSource(MediaItem.fromUri("$origin/api/v1/media/libraries/$library/items/$item/stream"))
                    p.addListener(object:Player.Listener {
                        override fun onIsPlayingChanged(isPlaying:Boolean) { view.keepScreenOn=isPlaying }
                        override fun onRenderedFirstFrame() { renderedFrame=true;status.text="Direct Play · Reprodução local" }
                        override fun onPlayerError(error:PlaybackException) {
                            status.text="Reprodução interrompida. Verifica a ligação e usa Tentar novamente. Se o formato não for suportado, experimenta outro ficheiro."
                            view.keepScreenOn=false
                        }
                        override fun onPlaybackStateChanged(state:Int) {
                            if(state==Player.STATE_ENDED) { position=0;report("stop",p.duration.coerceAtLeast(0),true);view.keepScreenOn=false }
                        }
                    })
                    p.setMediaSource(source);p.seekTo(position);p.prepare();p.playWhenReady=true
                    handler.postDelayed(heartbeat,10000)
                },{ status.text="Não foi possível autorizar este título. Verifica a conta, o servidor e a ligação." })
            }
        }
    }
    private fun report(event:String,millis:Long,paused:Boolean,final:Boolean=false) {
        if(eventBusy && !final)return
        eventBusy=true;val current=generation
        io.execute {
            val success=runCatching { MediaClient(this).event(library,item,event,millis.coerceAtLeast(0),paused) }.isSuccess
            runOnUiThread {
                eventBusy=false
                if(!final && foreground && current==generation && !success) {
                    position=observedPosition;handler.removeCallbacks(heartbeat);release()
                    status.text="Autorização ou progresso indisponível. Reprodução interrompida; verifica a ligação e tenta novamente."
                }
            }
        }
    }
    override fun dispatchKeyEvent(event:android.view.KeyEvent):Boolean =
        if(::view.isInitialized && view.dispatchKeyEvent(event))true else super.dispatchKeyEvent(event)
}
